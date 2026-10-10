import queue
import socket
import sys
import threading
import time
import urllib.request
import json

import pytest
pytest.importorskip('cryptography')
from desktop.runtime import Runtime
from desktop.tunnel import QuickTunnel, URL


def test_quick_tunnel_url_parser():
    assert URL.search('"url":"https://kind-cat.trycloudflare.com"').group(1) == 'kind-cat.trycloudflare.com'
    assert not URL.search('https://kind-cat.trycloudflare.com.evil.example')
    assert not URL.search('http://kind-cat.trycloudflare.com')


class Connector:
    def __init__(self, url='https://new-event.trycloudflare.com/', fail=False):
        self.url, self.fail = url, fail
        self.started, self.closed, self.dead = False, False, False

    def start(self, origin, stop):
        self.started = True
        self.origin = origin
        if self.fail:
            raise RuntimeError('Connector unavailable')
        return self.url

    def poll(self):
        return 1 if self.dead else None

    def close(self):
        self.closed = True


def ready(events):
    while True:
        kind, details = events.get(timeout=10)
        if kind == 'progress':
            continue
        assert kind == 'ready', details
        return details


def test_tunnel_url_published_and_local_admin_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv('POSE_SETUP_URL', 'http://old-setup/')
    connectors = []
    for name in ('first', 'second'):
        connector = Connector(f'https://{name}.trycloudflare.com/')
        connectors.append(connector)
        events = queue.Queue()
        runtime = Runtime(tmp_path, lambda *e: events.put(e), mode='tunnel', tunnel_factory=lambda: connector)
        worker = threading.Thread(target=runtime.run); worker.start()
        try:
            details = ready(events)
            assert details['url'].startswith(connector.url + '#invite=')
            assert details['setup_url'] is None and details['fingerprint'] is None
            assert details['admin_url'].startswith('http://127.0.0.1:')
            assert details['mode'] == 'tunnel'
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            state_url = connector.origin + 'api/state'
            with opener.open(state_url) as response:
                state = json.load(response)
            assert state['join_url'] is None and state['players'] == []
            assert state['setup_url'] is None
            # cloudflared forwards the original Host and HTTPS scheme to the loopback backend.
            login = urllib.request.Request(connector.origin + 'api/admin/login',
                data=json.dumps({'password': (tmp_path / 'admin-password.txt').read_text().strip()}).encode(),
                headers={'Content-Type': 'application/json', 'Host': name + '.trycloudflare.com',
                         'Origin': connector.url.rstrip('/'), 'X-Forwarded-Proto': 'https'})
            with pytest.raises(urllib.error.HTTPError) as exc:
                opener.open(login)
            assert exc.value.code == 403
            assert not (tmp_path / 'tls').exists()
        finally:
            runtime.stop(); worker.join(timeout=10)
        assert not worker.is_alive() and connector.closed
        assert events.get(timeout=2)[0] == 'stopped'
        import os
        assert os.environ['POSE_SETUP_URL'] == 'http://old-setup/'
    assert connectors[0].url != connectors[1].url


@pytest.mark.parametrize('startup_failure', [False, True])
def test_connector_failure_stops_backend_and_clears_readiness(tmp_path, startup_failure):
    connector = Connector(fail=startup_failure)
    events = queue.Queue()
    runtime = Runtime(tmp_path, lambda *e: events.put(e), mode='tunnel', tunnel_factory=lambda: connector)
    worker = threading.Thread(target=runtime.run); worker.start()
    try:
        if not startup_failure:
            ready(events)
            connector.dead = True
        while True:
            kind, details = events.get(timeout=10)
            if kind == 'progress':
                continue
            assert kind == 'error'
            break
        assert events.get(timeout=10)[0] == 'stopped'
    finally:
        runtime.stop(); worker.join(timeout=10)
    assert not worker.is_alive() and connector.closed
    from urllib.parse import urlsplit
    parsed = urlsplit(connector.origin)
    with socket.socket() as probe:
        probe.bind((parsed.hostname, parsed.port))


@pytest.fixture
def fake_process(tmp_path, monkeypatch):
    import subprocess
    script = tmp_path / 'connector.py'
    script.write_text('import time\nprint("https://fixture.trycloudflare.com", flush=True)\nprint("Registered tunnel connection", flush=True)\ntime.sleep(60)\n')
    original = subprocess.Popen
    captured = []
    def spawn(args, **kwargs):
        captured.append(args)
        return original([sys.executable, str(script)], **kwargs)
    monkeypatch.setattr('desktop.tunnel.subprocess.Popen', spawn)
    return captured


def test_connector_waits_for_health_and_closes_process(fake_process, monkeypatch):
    import io
    class Response(io.BytesIO):
        status = 200
    class Opener:
        def open(self, url, timeout):
            assert url == 'https://fixture.trycloudflare.com/api/health'
            return Response(b'{"status":"ok"}')
    monkeypatch.setattr('desktop.tunnel.urllib.request.build_opener', lambda *args: Opener())
    tunnel = QuickTunnel(executable='fixture')
    try:
        assert tunnel.start('http://127.0.0.1:1234/', threading.Event()) == 'https://fixture.trycloudflare.com/'
        assert '--no-autoupdate' in fake_process[0]
        assert '--config' in fake_process[0]
        assert tunnel.process.poll() is None
    finally:
        tunnel.close()
    assert tunnel.process.poll() is not None
    assert not tunnel.reader.is_alive()


def test_connector_timeout_cleans_process(fake_process, monkeypatch):
    class Opener:
        def open(self, *args, **kwargs):
            raise OSError('DNS not ready')
    monkeypatch.setattr('desktop.tunnel.urllib.request.build_opener', lambda *args: Opener())
    tunnel = QuickTunnel(executable='fixture', timeout=.3)
    try:
        with pytest.raises(RuntimeError, match='タイムアウト'):
            tunnel.start('http://127.0.0.1:1234/', threading.Event())
    finally:
        tunnel.close()
    assert tunnel.poll() is not None


def test_connector_cancel_during_startup(fake_process):
    stop = threading.Event()
    tunnel = QuickTunnel(executable='fixture')
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(tunnel.start('http://127.0.0.1:1234/', stop)))
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not tunnel.connected.is_set() and time.monotonic() < deadline:
            time.sleep(.01)
        stop.set(); worker.join(timeout=5)
        assert not worker.is_alive() and outcome == [None]
    finally:
        stop.set(); worker.join(timeout=5); tunnel.close()


def test_gui_tunnel_qr_changes_and_clears_on_disconnect(tmp_path, monkeypatch):
    import os
    if os.name != 'nt' and not os.environ.get('DISPLAY'):
        pytest.skip('GUI requires a display')
    tk = pytest.importorskip('tkinter')
    pytest.importorskip('qrcode')
    from desktop.gui import Window
    opened = []
    monkeypatch.setattr('desktop.gui.webbrowser.open', opened.append)
    connectors = iter([Connector('https://one.trycloudflare.com/'), Connector('https://two.trycloudflare.com/')])
    used = []
    def factory(directory, notify, **options):
        connector = next(connectors); used.append(connector)
        return Runtime(directory, notify, tunnel_factory=lambda: connector, **options)
    root = tk.Tk(); root.withdraw()
    window = Window(root, tmp_path, runtime_factory=factory)
    def until(predicate):
        deadline = time.monotonic() + 10
        while not predicate() and time.monotonic() < deadline:
            root.update(); time.sleep(.02)
        assert predicate(), window.status.get()
    try:
        until(lambda: bool(window.urls))
        assert window.url.get().startswith('https://one.trycloudflare.com/#invite=')
        assert window.qr_image.width() > 100
        assert not window.qr_choices.winfo_manager()
        assert str(window.remote_buttons[2]['state']) == 'disabled'
        runtime_before, thread_before = window.runtime, window.thread
        qr_before = str(window.qr['image'])
        window.language.set('English'); window.change_language()
        assert window.runtime is runtime_before and window.thread is thread_before
        assert str(window.qr['image']) == qr_before
        assert window.url.get().startswith('https://one.trycloudflare.com/#invite=')
        assert window.status.get().startswith('Running')
        assert window.start_button['text'] == 'Start server'
        assert window.quick_guide.get().startswith('Scan the QR')
        assert window.fingerprint.get().startswith('Pages, display names')
        from desktop.i18n import Translator
        assert Translator(tmp_path).language == 'en'
        window.open_details(); root.update()
        assert window.details.state() == 'normal'
        window.details.withdraw()
        window.open_admin()
        assert opened[0].startswith('http://127.0.0.1:')
        assert opened[0].endswith('/admin?lang=en')
        used[0].dead = True
        until(lambda: window.failed and not window.thread.is_alive())
        root.update()
        assert window.url.get() == ''
        assert window.status.get().startswith('Startup / runtime error: Internet connection ended.')
        assert not window.qr['image']
        window.start()
        until(lambda: bool(window.urls))
        assert window.url.get().startswith('https://two.trycloudflare.com/#invite=')
    finally:
        window.runtime.stop(); window.thread.join(timeout=10)
        root.destroy()


def test_actual_listeners_block_public_admin_and_rotate_desktop_qr(tmp_path):
    import httpx
    from urllib.parse import parse_qs, urlsplit
    connector = Connector()
    events = queue.Queue()
    runtime = Runtime(tmp_path, lambda *e: events.put(e), mode='tunnel', tunnel_factory=lambda: connector)
    worker = threading.Thread(target=runtime.run)
    worker.start()
    try:
        details = ready(events)
        admin_origin = details['admin_url'].removesuffix('admin')
        assert admin_origin != connector.origin
        password = (tmp_path / 'admin-password.txt').read_text().strip()
        with httpx.Client(base_url=admin_origin, trust_env=False) as local, httpx.Client(base_url=connector.origin, trust_env=False) as public:
            assert local.post('api/admin/login', json={'password':password}).status_code == 200
            initial = local.get('api/state').json()
            assert initial['join_url'] == details['url']
            invite = parse_qs(urlsplit(details['url']).fragment)['invite'][0]
            assert local.post('api/admin/join', json={'name':'Host PC'}).status_code == 200
            public.headers.update({'Cookie':'pose_session='+local.cookies['pose_session'],
                'Host':urlsplit(admin_origin).netloc, 'X-Forwarded-For':'127.0.0.1',
                'X-Forwarded-Host':urlsplit(admin_origin).netloc, 'X-Forwarded-Proto':'http'})
            assert public.post('api/admin/login', json={'password':password}).status_code == 403
            assert public.post('api/admin/action', json={'action':'end'}).status_code == 403
            assert public.get('api/state').json()['players'] == []
            public.headers.clear()
            assert public.post('api/join', json={'name':'Guest','invite_token':invite}).status_code == 200
            assert public.get('api/state').json()['players']
            assert not local.get('api/state?participant=1').json()['admin']
            local.post('api/admin/action', json={'action':'end'})
            local.post('api/admin/action', json={'action':'new_event'})
            updated = ready(events)
            assert updated['url'] != details['url']
            assert updated['admin_url'] == details['admin_url']
            assert public.get('api/state').json()['players'] == []
            assert public.post('api/join', json={'name':'Old QR','invite_token':invite}).status_code == 403
    finally:
        runtime.stop()
        worker.join(timeout=15)
    assert not worker.is_alive()
