import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .game import Game, GameError
from .access import RegistrationGuard, RequestBodyLimit
from .models import KeypointFrame, Settings
from .network import configured_public_url, detect_lan_ip, join_url
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent
COOKIE = "pose_session"
PARTICIPANT_COOKIE = "pose_pc_participant"
ENROLLMENT_COOKIE = "pose_enrollment"


class JoinBody(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    invite_token: str | None = Field(default=None, max_length=128)


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ActionBody(BaseModel):
    action: str = Field(max_length=30)
    name: str | None = Field(default=None, max_length=60)
    player_id: str | None = Field(default=None, max_length=64)


def create_app(data_dir=None, admin_password=None, local_admin_port=None):
    directory = Path(data_dir or os.environ.get("POSE_DATA_DIR", ROOT / "data"))
    peers = {}
    attempts = defaultdict(deque)
    registration = RegistrationGuard()

    def invitation_token():
        event_id = app.state.game.state["id"]
        invitation = app.state.store.get("invitation")
        if not invitation or invitation["event_id"] != event_id:
            invitation = {"event_id": event_id, "token": secrets.token_urlsafe(32)}
            app.state.store.put("invitation", invitation)
        return invitation["token"]

    def invitation_url(base_url):
        origin = join_url(base_url, app.state.lan_ip, app.state.public_url)
        return origin + "#invite=" + invitation_token() if origin else None

    def local_admin_allowed(connection):
        # The ASGI server address comes from the listening socket, not Host,
        # Origin, client IP, or any trusted/spoofed forwarding header.
        return local_admin_port is None or (
            tuple(connection.scope.get("server") or ()) == ("127.0.0.1", local_admin_port)
            and connection.headers.get("host") == f"127.0.0.1:{local_admin_port}")

    def visible_identity(identity):
        if identity and identity["role"] == "player":
            if not app.state.game.state["players"].get(identity["player_id"], {}).get("active"):
                return None
        return identity

    @asynccontextmanager
    async def lifespan(app):
        app.state.lan_ip = detect_lan_ip()
        app.state.public_url = configured_public_url()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        password = admin_password or os.environ.get("POSE_ADMIN_PASSWORD")
        if password is None:
            password_file = directory / "admin-password.txt"
            if not password_file.exists():
                fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(secrets.token_urlsafe(18) + "\n")
            password = password_file.read_text().strip()
            logging.getLogger("uvicorn.error").info("Admin password file: %s", password_file)
        if len(password) < 12:
            raise RuntimeError("POSE_ADMIN_PASSWORD must contain at least 12 characters")
        app.state.password = password
        app.state.store = Store(directory / "pose.sqlite3")
        app.state.game = Game(app.state.store)
        app.state.game.save()
        invitation_token()
        app.state.invitation_token = invitation_token
        app.state.invitation_url = invitation_url

        async def send(ws, payload):
            try:
                await asyncio.wait_for(ws.send_json(payload), timeout=2)
            except (RuntimeError, WebSocketDisconnect, asyncio.TimeoutError, OSError):
                with suppress(Exception):
                    await ws.close()

        async def ticker():
            while True:
                await asyncio.sleep(.5)
                app.state.game.tick()
                outgoing = []
                for ws, peer in list(peers.items()):
                    auth = app.state.store.auth(peer["token"])
                    if not auth:
                        with suppress(Exception):
                            await ws.close(code=4401)
                        continue
                    if auth["role"] == "player":
                        player = app.state.game.state["players"].get(auth["player_id"])
                        if not player or not player["active"]:
                            with suppress(Exception):
                                await ws.close(code=4403)
                            continue
                    outgoing.append(send(ws, snapshot(auth, str(ws.url), peer["participant_token"])))
                if outgoing:
                    await asyncio.gather(*outgoing)

        task = asyncio.create_task(ticker())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        for ws in list(peers):
            with suppress(Exception):
                await ws.close(code=1001)
        app.state.game.save()
        app.state.store.close()

    app = FastAPI(title="Pose Parallax", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(RequestBodyLimit)

    def snapshot(identity, base_url, participant_token=None):
        identity = visible_identity(identity)
        result = app.state.game.snapshot(identity)
        result["join_url"] = invitation_url(base_url) if result["admin"] else None
        setup_url = os.environ.get("POSE_SETUP_URL")
        result["setup_url"] = setup_url + "#invite=" + invitation_token() if result["admin"] and setup_url else None
        if not identity:
            result.update(players=[], round=None, history=[], me=None)
        participant = app.state.store.auth(participant_token)
        pid = participant.get("player_id") if participant else None
        result["admin_player_id"] = (pid if result["admin"] and
            app.state.game.state["players"].get(pid, {}).get("active") else None)
        return result

    def auth(request):
        identity = app.state.store.auth(request.cookies.get(COOKIE))
        if identity and identity["role"] == "admin" and not local_admin_allowed(request):
            return None
        return identity

    def admin(request):
        identity = auth(request)
        if not identity or identity["role"] != "admin":
            raise HTTPException(403, "管理者ログインが必要です。")
        return identity

    def same_origin(origin, host):
        return origin is not None and urlsplit(origin).netloc == host and urlsplit(origin).scheme in ("http", "https")

    @app.middleware("http")
    async def security_headers(request, call_next):
        if (request.url.path == "/admin" or request.url.path.startswith("/api/admin/")) and not local_admin_allowed(request):
            return JSONResponse({"detail": "管理画面は主催者PCから開いてください。"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and not same_origin(origin, request.headers.get("host")):
                return JSONResponse({"detail": "別サイトからの操作は許可されていません。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(GameError)
    async def game_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def set_session(response, request, role, player_id=None):
        old = request.cookies.get(COOKIE)
        if old:
            app.state.store.revoke(old)
        response.set_cookie(COOKIE, app.state.store.session(role, player_id), max_age=86400,
                            httponly=True, secure=request.url.scheme == "https", samesite="strict")

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/state")
    async def state(request: Request, response: Response):
        identity = (app.state.store.auth(request.cookies.get(PARTICIPANT_COOKIE))
                    if request.query_params.get("participant") == "1" else auth(request))
        if identity and identity["role"] == "admin" and not local_admin_allowed(request):
            identity = None
        if not registration.identity(request.cookies.get(ENROLLMENT_COOKIE)):
            response.set_cookie(ENROLLMENT_COOKIE, registration.cookie(), max_age=86400,
                                httponly=True, secure=request.url.scheme == "https", samesite="strict")
        return snapshot(identity, str(request.base_url), request.cookies.get(PARTICIPANT_COOKIE))

    @app.post("/api/admin/join")
    async def admin_join(body: JoinBody, request: Request, response: Response):
        admin(request)
        old = request.cookies.get(PARTICIPANT_COOKIE)
        identity = app.state.store.auth(old)
        if identity and identity["player_id"] in app.state.game.state["players"]:
            player = app.state.game.state["players"][identity["player_id"]]
            if player["active"]:
                return {"player_id": player["id"]}
            raise HTTPException(403, "このゲームから退出しました。次のグループの受付をお待ちください。")
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "表示名を入力してください。")
        pid = app.state.game.join(name)
        app.state.game.set_poser(pid)
        if old:
            app.state.store.revoke(old)
        response.set_cookie(PARTICIPANT_COOKIE, app.state.store.session("player", pid),
                            max_age=86400, httponly=True, secure=request.url.scheme == "https", samesite="strict")
        return {"player_id": pid}

    @app.post("/api/join")
    async def join(body: JoinBody, request: Request, response: Response):
        identity = auth(request)
        if identity and identity["role"] == "admin":
            raise HTTPException(409, "参加者として遊ぶ場合は別のブラウザで参加してください。")
        if identity and identity["player_id"] in app.state.game.state["players"]:
            player = app.state.game.state["players"][identity["player_id"]]
            if player["active"]:
                return {"player_id": player["id"]}
            raise HTTPException(403, "このゲームから退出しました。次のグループの受付をお待ちください。")
        if not registration.allow(request.client.host, request.cookies.get(ENROLLMENT_COOKIE)):
            raise HTTPException(429, "参加登録が多すぎます。1分ほど待ってから再試行してください。", headers={"Retry-After": "60"})
        if not body.invite_token or not hmac.compare_digest(body.invite_token.encode(), invitation_token().encode()):
            raise HTTPException(403, "主催者の最新のQRコードから参加してください。")
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "表示名を入力してください。")
        pid = app.state.game.join(name)
        set_session(response, request, "player", pid)
        return {"player_id": pid}

    @app.post("/api/admin/login")
    async def login(body: LoginBody, request: Request, response: Response):
        ip, now = request.client.host, time.monotonic()
        recent = attempts[ip]
        while recent and recent[0] < now - 60:
            recent.popleft()
        if len(recent) >= 5:
            raise HTTPException(429, "しばらく待ってからログインしてください。")
        recent.append(now)
        if not hmac.compare_digest(body.password.encode(), app.state.password.encode()):
            raise HTTPException(401, "パスワードが違います。")
        attempts.pop(ip, None)
        set_session(response, request, "admin")
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        identity = app.state.store.auth(token)
        if identity and identity["role"] == "admin" and not local_admin_allowed(request):
            raise HTTPException(403, "管理画面は主催者PCから開いてください。")
        if token:
            app.state.store.revoke(token)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.put("/api/admin/settings")
    async def settings(body: Settings, request: Request):
        admin(request)
        app.state.game.configure(body)
        return {"ok": True}

    @app.post("/api/admin/action")
    async def action(body: ActionBody, request: Request):
        admin(request)
        try:
            app.state.game.action(body.action, body.name, body.player_id)
        except ValueError as exc:
            raise GameError(str(exc)) from exc
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        token = ws.cookies.get(PARTICIPANT_COOKIE if ws.query_params.get("participant") == "1" else COOKIE)
        identity = app.state.store.auth(token)
        if not identity or (identity["role"] == "admin" and not local_admin_allowed(ws)) or not same_origin(ws.headers.get("origin"), ws.headers.get("host")):
            await ws.close(code=4401)
            return
        pid = identity.get("player_id")
        if pid:
            player = app.state.game.state["players"].get(pid)
            if not player or not player["active"]:
                await ws.close(code=4403)
                return
        await ws.accept()
        # A player has one authoritative camera connection; opening a new tab replaces the old one.
        for old_ws, old in list(peers.items()):
            if old["token"] == token:
                with suppress(Exception):
                    await old_ws.close(code=4409)
        peers[ws] = {"token": token, "pid": pid, "participant_token": ws.cookies.get(PARTICIPANT_COOKIE)}
        if pid:
            app.state.game.connections.add(pid)
        try:
            await ws.send_json(snapshot(identity, str(ws.url), ws.cookies.get(PARTICIPANT_COOKIE)))
            invalid = 0
            while True:
                message = await ws.receive_text()
                if len(message) > 8192:
                    await ws.close(code=1009)
                    break
                if not app.state.store.auth(token):
                    await ws.close(code=4401)
                    break
                if pid and not app.state.game.state["players"].get(pid, {}).get("active"):
                    await ws.close(code=4403)
                    break
                try:
                    data = json.loads(message)
                    if not isinstance(data, dict):
                        raise ValueError("Object required")
                    if data.get("type") in ("ready", "unready") and pid:
                        app.state.game.ready(pid, data.get("round_id"), data["type"] == "ready")
                    elif data.get("type") == "pose" and pid:
                        result = app.state.game.frame(pid, KeypointFrame.model_validate(data))
                        if result:
                            await ws.send_json({"type": "feedback", **result})
                except (ValueError, ValidationError):
                    invalid += 1
                    if invalid >= 3:
                        await ws.close(code=1008)
                        break
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            peers.pop(ws, None)
            if pid and not any(p["pid"] == pid for p in peers.values()):
                app.state.game.disconnect(pid)

    dist = ROOT / "dist"
    if dist.exists():
        for folder in ("assets", "models", "wasm", "licenses"):
            if (dist / folder).exists():
                app.mount("/" + folder, StaticFiles(directory=dist / folder), name=folder)

    @app.get("/{path:path}")
    async def index(path: str):
        if path == "inference-worker.js" and (dist / path).exists():
            return FileResponse(dist / path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})
        if path not in ("", "admin"):
            raise HTTPException(404)
        if not (dist / "index.html").exists():
            return JSONResponse({"detail": "Run npm run assets && npm run build, or use the Vite dev server."}, status_code=503)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
