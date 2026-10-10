from contextlib import ExitStack
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from server.app import create_app

PASSWORD = "test-password-for-admin"
ORIGIN = {"origin": "http://testserver"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, PASSWORD)) as client:
        yield client


def test_admin_requires_auth_and_origin(client):
    assert client.post("/api/admin/action", json={"action": "end"}).status_code == 403
    assert client.post("/api/admin/login", json={"password": PASSWORD}, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/admin/login", json={"password": PASSWORD}).status_code == 200
    assert client.get("/api/state").json()["admin"]
    assert client.post("/api/admin/action", json={"action": "end"}).status_code == 200
    assert client.post("/api/logout").status_code == 200
    assert client.post("/api/admin/action", json={"action": "end"}).status_code == 403


def test_login_throttle_and_join_validation(client):
    for _ in range(5):
        assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/admin/login", json={"password": PASSWORD}).status_code == 429
    assert client.post("/api/join", json={"name": "   ", "invite_token": client.app.state.invitation_token()}).status_code == 422
    assert client.post("/api/join", json={"name": "A" * 31, "invite_token": client.app.state.invitation_token()}).status_code == 422


def test_websocket_rejects_wrong_origin(client):
    client.post("/api/join", json={"name": "A", "invite_token": client.app.state.invitation_token()})
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass


def test_two_person_round_over_real_websockets(client):
    app = client.app
    admin_cookie = None
    client.post("/api/admin/login", json={"password": PASSWORD})
    admin_cookie = client.cookies.get("pose_session")
    settings = client.get("/api/state").json()["settings"]
    settings["hold_seconds"] = 0
    assert client.put("/api/admin/settings", json=settings).status_code == 200
    client.cookies.clear()
    a = client.post("/api/join", json={"name": "A", "invite_token": client.app.state.invitation_token()}).json()["player_id"]
    token_a = client.cookies.get("pose_session")
    # Repeated joining is idempotent and cannot create ghost players.
    assert client.post("/api/join", json={"name": "A again", "invite_token": client.app.state.invitation_token()}).json()["player_id"] == a
    client.cookies.clear()
    b = client.post("/api/join", json={"name": "B", "invite_token": client.app.state.invitation_token()}).json()["player_id"]
    token_b = client.cookies.get("pose_session")
    with ExitStack() as stack:
        sockets = {}
        for pid, token in [(a, token_a), (b, token_b)]:
            client.cookies.set("pose_session", token)
            sockets[pid] = stack.enter_context(client.websocket_connect("/ws", headers=ORIGIN))
            assert sockets[pid].receive_json()["me"] == pid
        client.cookies.set("pose_session", admin_cookie)
        assert client.post("/api/admin/action", json={"action": "setup"}).status_code == 200
        r = app.state.game.state["round"]
        for pid in (a, b):
            sockets[pid].send_json({"type": "ready", "round_id": r["id"]})
            while True:
                received = sockets[pid].receive_json()
                if received["type"] == "state" and any(p["id"] == pid and p["ready"] for p in received["players"]):
                    break
        assert client.post("/api/admin/action", json={"action": "start"}).status_code == 200
        observer = next(iter(r["views"]))
        sockets[observer].send_json({"type": "pose", "round_id": r["id"], "keypoints": r["views"][observer]["target"]})
        while True:
            data = sockets[observer].receive_json()
            if data["type"] == "feedback":
                assert data["cleared"]
                break
        final = client.get("/api/state").json()
        assert final["phase"] == "round_result"
        assert final["history"][0]["outcome"] == "cleared"
    # Same cookie resumes same identity after a disconnect.
    client.cookies.set("pose_session", token_a)
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        assert ws.receive_json()["me"] == a


def test_excluded_player_cannot_rejoin_current_event(client):
    pid = client.post("/api/join", json={"name": "A", "invite_token": client.app.state.invitation_token()}).json()["player_id"]
    token = client.cookies.get("pose_session")
    client.cookies.clear()
    client.post("/api/admin/login", json={"password": PASSWORD})
    assert client.post("/api/admin/action", json={"action": "remove", "player_id": pid}).status_code == 200
    client.cookies.set("pose_session", token)
    assert client.post("/api/join", json={"name": "Again", "invite_token": client.app.state.invitation_token()}).status_code == 403


def test_three_bad_frames_disconnect(client):
    client.post("/api/join", json={"name": "A", "invite_token": client.app.state.invitation_token()})
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        for _ in range(3):
            ws.send_json({"type": "pose", "round_id": "bad", "keypoints": [[0, 0, 1]]})
        with pytest.raises(WebSocketDisconnect):
            while True:
                ws.receive_json()


def test_admin_pc_join_preserves_admin_and_separate_participant_identity(client):
    assert client.post('/api/admin/join', json={'name':'PC'}).status_code == 403
    client.post('/api/admin/login', json={'password':PASSWORD})
    admin_token = client.cookies.get('pose_session')
    assert client.post('/api/admin/join', json={'name':'   '}).status_code == 422
    assert client.post('/api/admin/join', json={'name':'PC'}, headers={'origin':'https://evil.example'}).status_code == 403
    response = client.post('/api/admin/join', json={'name':'Host PC'})
    assert response.status_code == 200
    pid = response.json()['player_id']
    assert client.cookies.get('pose_session') == admin_token
    assert client.cookies.get('pose_pc_participant') != admin_token
    assert client.post('/api/admin/join', json={'name':'Duplicate'}).json()['player_id'] == pid
    state = client.get('/api/state').json()
    assert state['admin'] and state['admin_player_id'] == pid
    assert state['fixed_poser_id'] == pid and len(state['players']) == 1
    participant = client.get('/api/state?participant=1').json()
    assert participant['me'] == pid and not participant['admin']
    assert participant['settings'] is None and participant['admin_player_id'] is None
    assert client.post('/api/admin/action', json={'action':'set_poser','player_id':'unknown'}).status_code == 409
    assert client.post('/api/admin/action', json={'action':'set_poser'}).status_code == 200
    assert client.get('/api/state').json()['fixed_poser_id'] is None
    assert client.post('/api/admin/action', json={'action':'remove','player_id':pid}).status_code == 200
    assert client.get('/api/state').json()['admin_player_id'] is None
    assert client.post('/api/admin/join', json={'name':'Again'}).status_code == 403
    assert client.post('/api/admin/action', json={'action':'end'}).status_code == 200
    assert client.post('/api/admin/action', json={'action':'new_event'}).status_code == 200
    assert client.post('/api/admin/join', json={'name':'Next PC'}).json()['player_id'] != pid


def test_admin_and_pc_participant_websockets_coexist_and_can_start(client):
    client.post('/api/admin/login', json={'password':PASSWORD})
    admin_token = client.cookies.get('pose_session')
    pc = client.post('/api/admin/join', json={'name':'Host PC'}).json()['player_id']
    pc_token = client.cookies.get('pose_pc_participant')
    client.cookies.clear()
    observer = client.post('/api/join', json={'name':'Observer', "invite_token": client.app.state.invitation_token()}).json()['player_id']
    observer_token = client.cookies.get('pose_session')
    assert client.post('/api/admin/action',json={'action':'set_poser','player_id':observer}).status_code == 403
    with ExitStack() as stack:
        client.cookies.set('pose_session',admin_token)
        client.cookies.set('pose_pc_participant',pc_token)
        admin_ws = stack.enter_context(client.websocket_connect('/ws',headers=ORIGIN))
        assert admin_ws.receive_json()['admin']
        pc_ws = stack.enter_context(client.websocket_connect('/ws?participant=1',headers=ORIGIN))
        assert pc_ws.receive_json()['me'] == pc
        client.cookies.set('pose_session',observer_token)
        observer_ws = stack.enter_context(client.websocket_connect('/ws',headers=ORIGIN))
        assert observer_ws.receive_json()['me'] == observer
        client.cookies.set('pose_session',admin_token)
        assert client.post('/api/admin/action',json={'action':'setup'}).status_code == 200
        r = client.app.state.game.state['round']
        assert r['poser_id'] == pc
        for ws in (pc_ws,observer_ws):
            ws.send_json({'type':'ready','round_id':r['id']})
        while True:
            state = admin_ws.receive_json()
            if all(p['ready'] and p['connected'] for p in state['players']):
                break
        assert client.post('/api/admin/action',json={'action':'start'}).status_code == 200
        assert client.get('/api/state').json()['admin']
        assert client.get('/api/state?participant=1').json()['phase'] == 'playing'


def test_admin_pc_join_obeys_capacity_and_registration(client):
    client.post('/api/admin/login',json={'password':PASSWORD})
    for i in range(50):
        client.app.state.game.join(str(i))
    assert client.post('/api/admin/join',json={'name':'PC'}).status_code == 409
    client.app.state.game.remove(next(iter(client.app.state.game.state['players'])))
    client.app.state.game.action('registration')
    assert client.post('/api/admin/join',json={'name':'PC'}).status_code == 409
    assert len(client.app.state.game.active()) == 49
