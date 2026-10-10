from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from server.network import configured_public_url, detect_lan_ip, join_url
from server.app import create_app
from server.__main__ import main


def test_route_address_detection_does_not_send_packets(monkeypatch):
    monkeypatch.delenv("POSE_LAN_IP", raising=False)
    probe = MagicMock()
    probe.__enter__.return_value = probe
    probe.getsockname.return_value = ("192.168.21.130", 41000)
    monkeypatch.setattr("server.network.socket.socket", lambda *args: probe)
    assert detect_lan_ip() == "192.168.21.130"
    probe.send.assert_not_called()
    probe.sendto.assert_not_called()


def test_detection_falls_back_when_default_route_is_missing(monkeypatch):
    monkeypatch.delenv("POSE_LAN_IP", raising=False)
    probe = MagicMock()
    probe.__enter__.return_value = probe
    probe.connect.side_effect = OSError("No route")
    monkeypatch.setattr("server.network.socket.socket", lambda *args: probe)
    monkeypatch.setattr("server.network.socket.getaddrinfo", lambda *args: [
        (2, 1, 6, "", ("127.0.0.1", 0)), (2, 1, 6, "", ("192.168.1.8", 0))])
    assert detect_lan_ip() == "192.168.1.8"


@pytest.mark.parametrize("base,expected", [
    ("http://localhost:8000/", "http://192.168.21.130:8000/"),
    ("http://127.0.0.1:5173/", "http://192.168.21.130:5173/"),
    ("ws://[::1]:8000/ws", "http://192.168.21.130:8000/"),
    ("wss://pose.example.com/ws", "https://pose.example.com/"),
    ("https://192.168.1.2:8443/", "https://192.168.1.2:8443/"),
])
def test_join_url_preserves_external_scheme_host_and_port(base, expected):
    assert join_url(base, "192.168.21.130") == expected


def test_detection_failure_does_not_advertise_localhost():
    assert join_url("http://localhost:8000/", None) is None


def test_override_and_bad_ip(monkeypatch):
    monkeypatch.setenv("POSE_LAN_IP", "192.168.21.130")
    assert detect_lan_ip() == "192.168.21.130"
    monkeypatch.setenv("POSE_LAN_IP", "127.0.0.1")
    with pytest.raises(ValueError):
        detect_lan_ip()
    monkeypatch.setenv("POSE_PUBLIC_URL", "https://pose.example.com")
    assert configured_public_url() == "https://pose.example.com/"
    assert join_url("http://localhost:8000", None, configured_public_url()) == "https://pose.example.com/"
    monkeypatch.setenv("POSE_PUBLIC_URL", "https://pose.example.com/unsupported-path")
    with pytest.raises(ValueError):
        configured_public_url()


def test_http_and_websocket_snapshots_use_the_same_lan_url(tmp_path, monkeypatch):
    monkeypatch.setenv("POSE_LAN_IP", "192.168.21.130")
    monkeypatch.delenv("POSE_PUBLIC_URL", raising=False)
    with TestClient(create_app(tmp_path, "network-test-password"), base_url="http://localhost:8000") as client:
        assert client.get("/api/state").json()["join_url"] is None
        client.post("/api/admin/login", json={"password": "network-test-password"})
        assert client.get("/api/state").json()["join_url"].startswith("http://192.168.21.130:8000/#invite=")
        client.cookies.clear()
        client.post("/api/join", json={"name": "A", "invite_token": client.app.state.invitation_token()})
        with client.websocket_connect("ws://localhost:8000/ws", headers={"origin": "http://localhost:8000"}) as ws:
            assert ws.receive_json()["join_url"] is None
            assert ws.receive_json()["join_url"] is None


def test_launcher_binds_all_interfaces_and_prints_lan_url(monkeypatch, capsys):
    monkeypatch.setenv("POSE_LAN_IP", "192.168.21.130")
    monkeypatch.delenv("POSE_PUBLIC_URL", raising=False)
    run = MagicMock()
    monkeypatch.setattr("server.__main__.uvicorn.run", run)
    main(["--http", "--port", "8123"])
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["port"] == 8123
    assert "http://192.168.21.130:8123/" in capsys.readouterr().out
