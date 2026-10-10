from contextlib import ExitStack
from fastapi.testclient import TestClient
from server.app import create_app


def test_fifty_connected_players_can_complete_a_round(tmp_path):
    with TestClient(create_app(tmp_path, "capacity-test-password")) as client, ExitStack() as stack:
        client.post("/api/admin/login", json={"password": "capacity-test-password"})
        admin = client.cookies.get("pose_session")
        settings = client.get("/api/state").json()["settings"]
        settings["hold_seconds"] = 0
        assert client.put("/api/admin/settings", json=settings).status_code == 200
        sockets = {}
        for i in range(50):
            client.cookies.clear()
            response = client.post("/api/join", json={"name": f"Member {i + 1}", "invite_token": client.app.state.invitation_token()})
            assert response.status_code == 200
            pid = response.json()["player_id"]
            ws = stack.enter_context(client.websocket_connect("/ws", headers={"origin": "http://testserver"}))
            assert ws.receive_json()["me"] == pid
            sockets[pid] = ws
        client.cookies.clear()
        assert client.post("/api/join", json={"name": "51st", "invite_token": client.app.state.invitation_token()}).status_code == 409
        client.cookies.set("pose_session", admin)
        assert client.post("/api/admin/action", json={"action": "setup"}).status_code == 200
        r = client.app.state.game.state["round"]
        for ws in sockets.values():
            ws.send_json({"type": "ready", "round_id": r["id"]})
        for pid, ws in sockets.items():
            while True:
                data = ws.receive_json()
                if data["type"] == "state" and all(p["ready"] for p in data["players"]):
                    break
        assert client.post("/api/admin/action", json={"action": "start"}).status_code == 200
        for pid, view in r["views"].items():
            sockets[pid].send_json({"type": "pose", "round_id": r["id"], "keypoints": view["target"]})
        for pid in r["views"]:
            while True:
                data = sockets[pid].receive_json()
                if data["type"] == "feedback":
                    assert data["cleared"]
                    break
        result = client.get("/api/state").json()
        assert result["phase"] == "round_result"
        assert len(result["round"]["cleared"]) == 49
        assert result["history"][0]["outcome"] == "cleared"
