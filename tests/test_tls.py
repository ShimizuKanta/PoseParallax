from concurrent.futures import ThreadPoolExecutor
import shutil
import socket
import ssl
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest

from server.__main__ import main
from server.setup_page import create_setup_server
from server.tls import ensure_local_tls, openssl


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    return ensure_local_tls(tmp_path_factory.mktemp("local-ca"), "192.168.21.130")


def test_certificates_are_valid_for_lan_and_loopback(tls):
    for ip in ("192.168.21.130", "127.0.0.1", "::1"):
        assert openssl("verify", "-CAfile", tls.ca, "-verify_ip", ip, "-purpose", "sslserver", tls.cert).returncode == 0
    assert openssl("verify", "-CAfile", tls.ca, "-verify_hostname", "localhost", tls.cert).returncode == 0
    assert tls.key.stat().st_mode & 0o777 == 0o600
    assert (tls.ca.parent / "root-ca-key.pem").stat().st_mode & 0o777 == 0o600


def test_restart_reuses_ca_and_valid_leaf(tls):
    cert, root = tls.cert.read_bytes(), tls.ca.read_bytes()
    reused = ensure_local_tls(tls.ca.parent, "192.168.21.130")
    assert reused.cert.read_bytes() == cert
    assert reused.ca.read_bytes() == root


def test_ip_change_renews_leaf_without_reinstalling_ca(tls, tmp_path):
    shutil.copytree(tls.ca.parent, tmp_path / "tls")
    renewed = ensure_local_tls(tmp_path / "tls", "192.168.21.131")
    assert renewed.ca.read_bytes() == tls.ca.read_bytes()
    assert renewed.cert.read_bytes() != tls.cert.read_bytes()
    assert openssl("verify", "-CAfile", renewed.ca, "-verify_ip", "192.168.21.131", renewed.cert).returncode == 0


def test_missing_ca_key_fails_without_rotating_identity(tls, tmp_path):
    (tmp_path / "root-ca.pem").write_bytes(tls.ca.read_bytes())
    with pytest.raises(RuntimeError, match="片方"):
        ensure_local_tls(tmp_path, "192.168.21.130")
    assert (tmp_path / "root-ca.pem").read_bytes() == tls.ca.read_bytes()


def test_real_tls_handshake_with_explicit_ca_trust(tls):
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(tls.cert, tls.key)
    client_context = ssl.create_default_context(cafile=tls.ca)
    with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as pool:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            raw, _ = listener.accept()
            with server_context.wrap_socket(raw, server_side=True) as secure:
                assert secure.recv(4) == b"ping"
                secure.sendall(b"pong")

        future = pool.submit(serve)
        with socket.create_connection(listener.getsockname(), timeout=5) as raw:
            with client_context.wrap_socket(raw, server_hostname="192.168.21.130") as secure:
                secure.sendall(b"ping")
                assert secure.recv(4) == b"pong"
        future.result(timeout=5)


def test_setup_server_only_distributes_public_certificate(tls):
    server = create_setup_server("127.0.0.1", 0, "https://192.168.21.130:8443/", tls)
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    root = f"http://127.0.0.1:{server.server_port}"
    try:
        with client.open(root) as response:
            text = response.read().decode()
            assert "https://192.168.21.130:8443/" in text
            assert "証明書信頼設定" in text
            assert tls.fingerprint in text
        for filename in ("pose-parallax-ca.crt", "pose-parallax-ca.cer"):
            with client.open(root + "/" + filename) as response:
                assert response.read() == tls.ca_der
        for path, expected in [("/root-ca-key.pem", 404), ("/data/tls/server-key.pem", 404),
                               ("/../root-ca-key.pem", 404), ("/api/state", 426), ("/ws", 426)]:
            with pytest.raises(urllib.error.HTTPError) as error:
                client.open(root + path)
            assert error.value.code == expected
        request = urllib.request.Request(root + "/api/admin/login", data=b'{}', method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            client.open(request)
        assert error.value.code == 501
    finally:
        server.shutdown()
        server.server_close()


def test_default_launcher_is_https_and_advertises_setup_url(tls, monkeypatch, capsys):
    monkeypatch.setenv("POSE_LAN_IP", "192.168.21.130")
    monkeypatch.delenv("POSE_PORT", raising=False)
    monkeypatch.delenv("POSE_PUBLIC_URL", raising=False)
    monkeypatch.setenv("POSE_SETUP_URL", "")
    run, setup = MagicMock(), MagicMock()
    monkeypatch.setattr("server.__main__.ensure_local_tls", lambda *args: tls)
    monkeypatch.setattr("server.__main__.create_setup_server", setup)
    monkeypatch.setattr("server.__main__.uvicorn.run", run)
    main([])
    assert run.call_args.kwargs["port"] == 8443
    assert run.call_args.kwargs["ssl_certfile"] == str(tls.cert)
    assert run.call_args.kwargs["ssl_keyfile"] == str(tls.key)
    assert setup.call_args.args[:3] == ("0.0.0.0", 8000, "https://192.168.21.130:8443/")
    assert setup.return_value.shutdown.called
    assert "http://192.168.21.130:8000/" in capsys.readouterr().out


def test_conflicting_ports_are_rejected():
    with pytest.raises(SystemExit):
        main(["--port", "8000"])
