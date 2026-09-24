"""Real TLS/WSS tests with certificate validation enabled, using a temporary CA."""
import json
import os
import socket
import ssl
import subprocess
import sys
import time

import httpx
from websockets.sync.client import connect


def unused_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_https_login_secure_cookie_wss_and_certificate_setup(tmp_path):
    port, setup_port = unused_port(), unused_port()
    while setup_port == port:
        setup_port = unused_port()
    origin = f"https://127.0.0.1:{port}"
    environment = {**os.environ, "POSE_DATA_DIR": str(tmp_path), "POSE_ADMIN_PASSWORD": "https-test-password",
                   "POSE_LAN_IP": "192.0.2.40", "POSE_PUBLIC_URL": origin, "POSE_SETUP_URL": ""}
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen([sys.executable, "-m", "server", "--host", "127.0.0.1", "--port", str(port),
                                    "--setup-port", str(setup_port)], env=environment, stdout=log, stderr=log)
        try:
            ca = tmp_path / "tls/root-ca.pem"
            for _ in range(150):
                if process.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                if ca.exists():
                    try:
                        context = ssl.create_default_context(cafile=ca)
                        with httpx.Client(verify=context, trust_env=False, timeout=.5) as probe:
                            if probe.get(origin + "/api/health").status_code == 200:
                                break
                    except (httpx.HTTPError, ssl.SSLError):
                        pass
                time.sleep(.1)
            else:
                raise AssertionError("HTTPS server did not become ready")
            with httpx.Client(base_url=origin, verify=context, trust_env=False) as client:
                state = client.get("/api/state").json()
                assert state["join_url"] == origin + "/"
                assert state["setup_url"] == f"http://192.0.2.40:{setup_port}/"
                login = client.post("/api/admin/login", json={"password": "https-test-password"}, headers={"Origin": origin})
                assert login.status_code == 200
                cookie_header = login.headers["set-cookie"].lower()
                assert "secure" in cookie_header and "httponly" in cookie_header
                cookie = "pose_session=" + client.cookies["pose_session"]
                with connect(f"wss://127.0.0.1:{port}/ws", ssl=context, origin=origin,
                             additional_headers={"Cookie": cookie}, proxy=None, open_timeout=5) as ws:
                    snapshot = json.loads(ws.recv(timeout=5))
                    assert snapshot["admin"]
                    assert snapshot["join_url"] == origin + "/"
                    assert json.loads(ws.recv(timeout=5))["type"] == "state"
                assert client.get("/data/tls/root-ca-key.pem").status_code == 404
            with httpx.Client(base_url=f"http://127.0.0.1:{setup_port}", trust_env=False) as setup:
                assert setup.get("/").status_code == 200
                assert setup.get("/pose-parallax-ca.cer").content == ssl.PEM_cert_to_DER_cert(ca.read_text())
                assert setup.get("/api/state").status_code == 426
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
