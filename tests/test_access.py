from contextlib import ExitStack
import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.access import RegistrationGuard, RequestBodyLimit
from server.app import create_app

PASSWORD = "security-test-password"


def test_http_body_limit_precedes_json_and_registration(tmp_path):
    with TestClient(create_app(tmp_path, PASSWORD)) as client:
        payload = json.dumps({'name': 'Invited', 'invite_token': client.app.state.invitation_token()}).encode()
        response = client.post('/api/join', content=payload + b' ' * 16384,
                               headers={'content-type': 'application/json'})
        assert response.status_code == 413
        assert client.app.state.game.active() == []
        # A valid JSON body exactly at the limit still reaches the endpoint.
        assert client.post('/api/join', content=payload.ljust(16384, b' '),
                           headers={'content-type': 'application/json'}).status_code == 200


@pytest.mark.parametrize('sizes,accepted', [([0], True), ([8192, 8192], True), ([8192, 8192, 1, 1000], False)])
def test_streamed_body_limit_without_content_length(sizes, accepted):
    async def check():
        chunks = iter(sizes)
        received, sent, called = [], [], []

        async def receive():
            size = next(chunks)
            received.append(size)
            return {'type': 'http.request', 'body': b'x' * size, 'more_body': True}

        async def bounded_receive():
            message = await receive()
            message['more_body'] = len(received) < len(sizes)
            return message

        async def send(message):
            sent.append(message)

        async def endpoint(scope, receive, send):
            called.append((await receive())['body'])

        await RequestBodyLimit(endpoint)({'type': 'http'}, bounded_receive, send)
        if accepted:
            assert called == [b'x' * sum(sizes)]
        else:
            assert not called and sent[0]['status'] == 413
            assert received == [8192, 8192, 1]  # Stop before reading the remaining body.

    asyncio.run(check())


def test_private_state_invitation_rotation_and_exclusion(tmp_path):
    with TestClient(create_app(tmp_path, PASSWORD)) as client:
        client.post('/api/admin/login', json={'password': PASSWORD})
        admin_cookie = client.cookies.get('pose_session')
        old_url = client.get('/api/state').json()['join_url']
        invite = parse_qs(urlsplit(old_url).fragment)['invite'][0]
        assert client.app.state.invitation_token() == invite
        client.cookies.clear()
        assert client.post('/api/join', json={'name': 'No invite'}).status_code == 403
        assert client.post('/api/join', json={'name': 'Wrong', 'invite_token': 'bad'}).status_code == 403
        joined = client.post('/api/join', json={'name': 'Secret name', 'invite_token': invite})
        assert joined.status_code == 200
        player = joined.json()['player_id']
        player_cookie = client.cookies.get('pose_session')
        assert client.post('/api/join', json={'name':'Reconnect without invite'}).json()['player_id'] == player
        assert client.get('/api/state').json()['players'][0]['name'] == 'Secret name'
        client.cookies.clear()
        client.cookies.set('pose_session', admin_cookie)
        assert client.post('/api/admin/join', json={'name':'Secret host'}).status_code == 200
        assert client.post('/api/admin/action', json={'action':'setup'}).status_code == 200
        assert client.post('/api/admin/action', json={'action':'skip'}).status_code == 200
        assert client.get('/api/state').json()['history']
        client.cookies.clear()
        public = client.get('/api/state').json()
        assert public['players'] == [] and public['history'] == [] and public['round'] is None
        assert public['me'] is None and public['join_url'] is None and public['setup_url'] is None
        assert 'Secret name' not in client.get('/api/state').text
        client.cookies.set('pose_session', admin_cookie)
        client.post('/api/admin/action', json={'action': 'remove', 'player_id': player})
        client.cookies.set('pose_session', player_cookie)
        assert client.get('/api/state').json()['players'] == []
        client.cookies.set('pose_session', admin_cookie)
        client.post('/api/admin/action', json={'action': 'end'})
        client.post('/api/admin/action', json={'action': 'new_event'})
        new_invite = client.app.state.invitation_token()
        assert new_invite != invite
        client.cookies.clear()
        assert client.post('/api/join', json={'name': 'Old', 'invite_token': invite}).status_code == 403
        assert client.post('/api/join', json={'name': 'New', 'invite_token': new_invite}).status_code == 200
    with TestClient(create_app(tmp_path, PASSWORD)) as client:
        assert client.app.state.invitation_token() == new_invite


def test_registration_limits_expire_and_support_shared_wifi():
    now = [0]
    guard = RegistrationGuard(clock=lambda: now[0])
    cookie = guard.cookie()
    assert guard.identity(cookie)
    assert guard.identity(cookie + 'bad') is None
    assert guard.identity('wrong.é') is None
    assert all(guard.allow('same-ip', guard.cookie()) for _ in range(50))
    assert all(guard.allow('other-ip', cookie) for _ in range(3))
    assert not guard.allow('other-ip', cookie)
    now[0] = 60
    assert guard.allow('other-ip', cookie)
    guard = RegistrationGuard(clock=lambda: now[0])
    assert all(guard.allow('same-ip', None) for _ in range(60))
    assert not guard.allow('same-ip', None)
    assert all(guard.allow('other-ip', None) for _ in range(59))
    assert not guard.allow('third-ip', None)


def test_http_registration_throttles_before_checking_invite(tmp_path):
    with TestClient(create_app(tmp_path, PASSWORD)) as client:
        client.get('/api/state')
        for _ in range(3):
            assert client.post('/api/join', json={'name':'A','invite_token':'bad'}).status_code == 403
        response = client.post('/api/join', json={'name':'A','invite_token':client.app.state.invitation_token()})
        assert response.status_code == 429 and response.headers['retry-after'] == '60'
        assert client.app.state.game.active() == []


def test_admin_restricted_by_listener_not_forwarding_headers(tmp_path):
    app = create_app(tmp_path, PASSWORD, local_admin_port=8124)
    with ExitStack() as stack:
        local = stack.enter_context(TestClient(app, base_url='http://127.0.0.1:8124'))
        # Share the lifespan/database; the public client only changes the ASGI listener address.
        public = TestClient(app, base_url='http://127.0.0.1:8123')
        assert local.post('/api/admin/login', json={'password': PASSWORD}).status_code == 200
        admin_cookie = local.cookies.get('pose_session')
        for headers in ({}, {'host':'127.0.0.1:8124','x-forwarded-for':'127.0.0.1',
                             'x-forwarded-host':'127.0.0.1:8124','x-forwarded-proto':'http'}):
            public.cookies.set('pose_session', admin_cookie)
            assert public.get('/admin', headers=headers).status_code == 403
            for path, body in [('login', {'password': PASSWORD}), ('join', {'name':'PC'}),
                               ('action', {'action':'end'})]:
                assert public.post('/api/admin/'+path, json=body, headers=headers).status_code == 403
            assert public.put('/api/admin/settings', json={}, headers=headers).status_code == 403
            assert not public.get('/api/state', headers=headers).json()['admin']
        public.cookies.set('pose_pc_participant', admin_cookie)
        assert not public.get('/api/state?participant=1').json()['admin']
        assert public.post('/api/logout').status_code == 403
        assert local.post('/api/admin/action', json={'action':'registration'}, headers={'host':'attacker.example'}).status_code == 403
        with pytest.raises(WebSocketDisconnect):
            with public.websocket_connect('/ws', headers={'origin':'http://127.0.0.1:8123'}):
                pass
        assert local.get('/api/state').json()['admin']
        assert local.post('/api/admin/join', json={'name':'PC'}).status_code == 200
        assert not local.get('/api/state?participant=1').json()['admin']
