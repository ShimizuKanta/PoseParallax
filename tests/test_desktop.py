import queue
import socket
import ssl
import threading
import urllib.request
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

import pytest
pytest.importorskip('cryptography', reason='Install requirements-desktop.txt for desktop tests')
from cryptography import x509
from desktop.certificates import ensure_tls
from desktop.runtime import InstanceLock, Runtime, data_directory


def test_setup_link_preserves_invitation_and_language(monkeypatch):
    from desktop.gui import Window
    window = object.__new__(Window)
    window.urls = {'setup_url': 'http://127.0.0.1:8000/#invite=original-token'}
    opened = []
    monkeypatch.setattr('desktop.gui.webbrowser.open', opened.append)
    for language in ('ja', 'en'):
        window.translator = SimpleNamespace(language=language)
        window.open_setup()
        url = urlsplit(opened[-1])
        assert parse_qs(url.query) == {'lang': [language]}
        assert parse_qs(url.fragment) == {'invite': ['original-token']}


def test_persistent_directory(monkeypatch, tmp_path):
    monkeypatch.delenv('POSE_DATA_DIR', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert data_directory() == tmp_path / 'PoseParallax'
    monkeypatch.setenv('POSE_DATA_DIR', str(tmp_path / 'custom'))
    assert data_directory() == tmp_path / 'custom'


@pytest.mark.parametrize('existing', [None, b'', b'0'])
def test_instance_lock_released(tmp_path, existing):
    if existing is not None:
        (tmp_path / 'desktop.lock').write_bytes(existing)
    lock = InstanceLock(tmp_path)
    try:
        with pytest.raises(RuntimeError):
            InstanceLock(tmp_path)
    finally:
        lock.close()
    InstanceLock(tmp_path).close()


def test_certificate_reuse_and_ip_change(tmp_path):
    tls = ensure_tls(tmp_path, '192.168.1.2')
    old_ca, old_cert = tls.ca.read_bytes(), tls.cert.read_bytes()
    ensure_tls(tmp_path, '192.168.1.2')
    assert tls.cert.read_bytes() == old_cert
    ensure_tls(tmp_path, '192.168.1.3')
    assert tls.ca.read_bytes() == old_ca
    assert tls.cert.read_bytes() != old_cert
    cert = x509.load_pem_x509_certificate(tls.cert.read_bytes())
    cert.verify_directly_issued_by(x509.load_pem_x509_certificate(old_ca))
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(tls.cert, tls.key)
    tls.ca.unlink()
    with pytest.raises(RuntimeError, match='片方'):
        ensure_tls(tmp_path, '192.168.1.3')


def launch(tmp_path, **kwargs):
    events = queue.Queue()
    runtime = Runtime(tmp_path, lambda *event: events.put(event), host='127.0.0.1',
                      address='127.0.0.1', setup_port=0, **kwargs)
    worker = threading.Thread(target=runtime.run)
    worker.start()
    return runtime, worker, events


def shutdown(runtime, worker):
    runtime.stop(); worker.join(timeout=15)
    assert not worker.is_alive()


def test_https_onboarding_stop_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('POSE_PUBLIC_URL', 'https://external.example/')
    previous_password = None
    for _ in range(2):
        runtime, worker, events = launch(tmp_path, port=0)
        try:
            kind, details = events.get(timeout=20)
            assert kind == 'ready', details
            context = ssl.create_default_context(cafile=str(tmp_path / 'tls/root-ca.pem'))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
            with opener.open(details['url'].split('#')[0] + 'api/health', timeout=5) as response:
                assert response.status == 200
            with opener.open(details['setup_url'].split('#')[0] + 'pose-parallax-ca.cer', timeout=5) as response:
                assert x509.load_der_x509_certificate(response.read())
            with pytest.raises(urllib.error.HTTPError) as exc:
                opener.open(details['setup_url'].split('#')[0] + 'api/state', timeout=5)
            assert exc.value.code == 426
            password = (tmp_path / 'admin-password.txt').read_text()
            if previous_password:
                assert password == previous_password
            previous_password = password
        finally:
            shutdown(runtime, worker)
        assert events.get(timeout=2) == ('stopped', None)
    import os
    assert os.environ['POSE_PUBLIC_URL'] == 'https://external.example/'
    assert (tmp_path / 'pose.sqlite3').exists()


def test_port_conflict_is_reported_and_retry_works(tmp_path):
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0)); occupied.listen()
        runtime, worker, events = launch(tmp_path, port=occupied.getsockname()[1])
        try:
            assert events.get(timeout=20)[0] == 'error'
        finally:
            shutdown(runtime, worker)
        assert events.get(timeout=2)[0] == 'stopped'
    runtime, worker, events = launch(tmp_path, port=0)
    try:
        assert events.get(timeout=20)[0] == 'ready'
    finally:
        shutdown(runtime, worker)


def test_cancel_before_start(tmp_path):
    events = []
    runtime = Runtime(tmp_path, lambda *event: events.append(event), address='127.0.0.1', port=0, setup_port=0)
    runtime.stop(); runtime.run()
    assert events == [('stopped', None)]


def test_gui_qr_and_shutdown(tmp_path):
    import os
    import time
    if os.name != 'nt' and not os.environ.get('DISPLAY'):
        pytest.skip('GUI test requires a desktop display')
    tk = pytest.importorskip('tkinter')
    pytest.importorskip('qrcode')
    from desktop.gui import Window
    root = tk.Tk()
    root.withdraw()
    window = Window(root, tmp_path, runtime_factory=lambda folder, notify, **kwargs: Runtime(
        folder, notify, host='127.0.0.1', address='127.0.0.1', port=0, setup_port=0))
    deadline = time.monotonic() + 20
    try:
        while not window.urls and time.monotonic() < deadline:
            root.update(); time.sleep(.02)
        assert window.urls, window.status.get()
        assert window.url.get().startswith('http://127.0.0.1:')
        assert window.qr_image.width() >= 100
        window.qr_mode.set('url'); window.update_qr()
        assert window.url.get().startswith('https://127.0.0.1:')
        window.stop(confirm=False)
        window.thread.join(timeout=15)
        root.update()
        assert not window.thread.is_alive()
        assert window.url.get() == ''
    finally:
        if window.runtime:
            window.runtime.stop()
        if window.thread:
            window.thread.join(timeout=15)
        root.destroy()
    # No Window -> Runtime -> notify -> Window cycle may survive teardown:
    # its Tk variables would otherwise be finalized during a later server GC.
    import weakref
    reference = weakref.ref(window)
    del window
    assert reference() is None


def test_onboarding_port_conflict_releases_https_port(tmp_path):
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        https_port = available.getsockname()[1]
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0)); occupied.listen()
        events = []
        runtime = Runtime(tmp_path, lambda *event: events.append(event), host='127.0.0.1',
                          address='127.0.0.1', port=https_port, setup_port=occupied.getsockname()[1])
        runtime.run()
        assert [kind for kind, _ in events] == ['error', 'stopped']
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', https_port))
