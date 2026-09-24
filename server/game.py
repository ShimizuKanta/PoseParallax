import copy
import random
import time
import uuid
from .matching import match
from .models import Settings
from .poses import POSES, make_view


class GameError(ValueError):
    pass


class Game:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.defaults = Settings(**store.get("defaults", {}))
        self.state = store.get("current") or self.empty("Pose Parallax")
        self.connections = set()
        self.live = {}
        self.all_since = None
        if self.state["phase"] in ("round_setup", "playing"):
            self.finish("server_restart")

    def empty(self, name):
        return {"id": uuid.uuid4().hex, "name": name, "phase": "waiting", "registration_open": True,
                "players": {}, "round": None, "history": [], "created_at": self.clock()}

    def save(self):
        self.store.put("current", self.state)
        self.store.put("event:" + self.state["id"], self.state)

    def configure(self, settings):
        self.defaults = settings
        self.store.put("defaults", settings.model_dump())

    def join(self, name):
        if not self.state["registration_open"] or self.state["phase"] != "waiting":
            raise GameError("参加受付は終了しています。管理者にお声がけください。")
        if len(self.active()) >= 50:
            raise GameError("参加人数の上限（50人）に達しました。")
        player = {"id": uuid.uuid4().hex, "name": name, "active": True, "poser_count": 0}
        self.state["players"][player["id"]] = player
        self.save()
        return player["id"]

    def active(self):
        return [p for p in self.state["players"].values() if p["active"]]

    def setup(self):
        if self.state["phase"] not in ("waiting", "round_result"):
            raise GameError("今は次のラウンドを準備できません。")
        players = self.active()
        if len(players) < 2:
            raise GameError("2人以上の参加者が必要です。")
        if len(self.state["history"]) >= self.defaults.rounds:
            self.state["phase"] = "final_result"
            self.save()
            return
        fewest = min(p["poser_count"] for p in players)
        poser = random.choice([p for p in players if p["poser_count"] == fewest])
        pose = copy.deepcopy(random.choice(POSES))
        views = {p["id"]: make_view(pose, self.defaults) for p in players if p["id"] != poser["id"]}
        self.state["round"] = {"id": uuid.uuid4().hex, "number": len(self.state["history"]) + 1,
                               "poser_id": poser["id"], "pose": pose, "views": views,
                               "settings": self.defaults.model_dump(), "started_at": None,
                               "ended_at": None, "cleared": {}, "excluded": [], "outcome": None}
        poser["poser_count"] += 1
        self.state["phase"] = "round_setup"
        self.state["registration_open"] = False
        self.live, self.all_since = {}, None
        self.save()

    def observers(self):
        r = self.state["round"]
        return [pid for pid in r["views"] if pid not in r["excluded"]] if r else []

    def start(self):
        if self.state["phase"] != "round_setup":
            raise GameError("準備中のラウンドがありません。")
        r = self.state["round"]
        required = [r["poser_id"], *self.observers()]
        if any(pid not in self.connections for pid in required):
            raise GameError("未接続の参加者がいます。再接続を待つか、参加者を除外してください。")
        if any(not self.live.get(pid, {}).get("ready") for pid in required):
            raise GameError("全員の準備完了を待ってください。")
        r["started_at"] = self.clock()
        self.state["phase"] = "playing"
        self.save()

    def ready(self, pid, round_id, ready=True):
        if self.state["phase"] != "round_setup" or self.state["round"]["id"] != round_id:
            return
        if pid in [self.state["round"]["poser_id"], *self.observers()]:
            self.live.setdefault(pid, {})["ready"] = ready

    def disconnect(self, pid):
        self.connections.discard(pid)
        if pid in self.live:
            self.live[pid].update(ready=False, matched=False, since=None)
        self.all_since = None

    def frame(self, pid, frame):
        r = self.state["round"]
        if self.state["phase"] != "playing" or frame.round_id != r["id"] or pid not in self.observers():
            return None
        now = self.clock()
        if now - r["started_at"] >= r["settings"]["round_seconds"]:
            self.tick()
            return None
        old = self.live.get(pid, {})
        if now - old.get("last", 0) < .1:
            return None  # Hard ceiling of ten scoring frames per second per participant.
        settings = Settings(**r["settings"])
        result = match(r["views"][pid]["target"], frame.keypoints, settings)
        since = old.get("since") if old.get("matched") and now - old.get("last", 0) <= 1 else None
        if result["matched"]:
            since = now if since is None else since
        else:
            since = None
        self.live[pid] = {**result, "last": now, "since": since, "ready": True}
        if settings.clear_mode == "latched" and since is not None and now - since >= settings.hold_seconds:
            if pid not in r["cleared"]:
                r["cleared"][pid] = now
                self.save()
        self.tick()
        return {**result, "hold": 0 if since is None else round(now - since, 2),
                "cleared": pid in r["cleared"]}

    def tick(self):
        if self.state["phase"] != "playing":
            return
        r, now = self.state["round"], self.clock()
        if now - r["started_at"] >= r["settings"]["round_seconds"]:
            self.finish("timeout")
            return
        observers = self.observers()
        if not observers:
            self.finish("cancelled")
            return
        if r["settings"]["clear_mode"] == "latched":
            if all(pid in r["cleared"] for pid in observers):
                self.finish("cleared")
            return
        for pid in observers:
            live = self.live.get(pid, {})
            if now - live.get("last", 0) > 1 or pid not in self.connections:
                live.update(matched=False, since=None)
        if not all(self.live.get(pid, {}).get("matched") for pid in observers):
            self.all_since = None
            return
        self.all_since = max(now if self.all_since is None else self.all_since,
                             max(self.live[pid]["since"] for pid in observers))
        if now - self.all_since >= r["settings"]["hold_seconds"]:
            r["cleared"] = {pid: now for pid in observers}
            self.finish("cleared")

    def finish(self, outcome):
        if self.state["phase"] not in ("round_setup", "playing"):
            raise GameError("進行中のラウンドがありません。")
        r = self.state["round"]
        r["ended_at"] = self.clock()
        r["elapsed"] = round(r["ended_at"] - r["started_at"], 2) if r["started_at"] is not None else None
        r["outcome"] = outcome
        r["participants"] = {pid: p["name"] for pid, p in self.state["players"].items()
                              if pid == r["poser_id"] or pid in r["views"]}
        self.state["history"].append(copy.deepcopy(r))
        self.state["phase"] = "round_result"
        self.save()

    def remove(self, pid):
        if pid not in self.state["players"]:
            raise GameError("参加者が見つかりません。")
        self.state["players"][pid]["active"] = False
        self.disconnect(pid)
        r = self.state["round"]
        if r and self.state["phase"] in ("round_setup", "playing"):
            if pid == r["poser_id"]:
                self.finish("poser_left")
            else:
                if pid in r["views"] and pid not in r["excluded"]:
                    r["excluded"].append(pid)
                if not self.observers():
                    self.finish("cancelled")
                else:
                    self.tick()
        self.save()

    def action(self, action, name=None, player_id=None):
        if action == "setup":
            self.setup()
        elif action == "start":
            self.start()
        elif action in ("skip", "cancel"):
            self.finish("skipped" if action == "skip" else "cancelled")
        elif action == "remove":
            self.remove(player_id)
        elif action == "end":
            if self.state["phase"] in ("round_setup", "playing"):
                self.finish("cancelled")
            self.state["phase"] = "final_result"
            self.state["registration_open"] = False
        elif action == "registration":
            if self.state["phase"] != "waiting":
                raise GameError("待機中のみ受付を変更できます。")
            self.state["registration_open"] = not self.state["registration_open"]
        elif action == "new_event":
            if self.state["phase"] != "final_result":
                raise GameError("現在のゲームを終了してから次のグループを作成してください。")
            self.save()
            self.state = self.empty(name or "Pose Parallax")
            self.live, self.connections, self.all_since = {}, set(), None
        else:
            raise GameError("不明な操作です。")
        self.save()

    def snapshot(self, auth=None):
        auth = auth or {}
        admin, pid = auth.get("role") == "admin", auth.get("player_id")
        now, r = self.clock(), self.state["round"]
        players = [{**p, "connected": p["id"] in self.connections,
                    "ready": self.live.get(p["id"], {}).get("ready", False),
                    "score": self.live.get(p["id"], {}).get("score", 0),
                    "matched": self.live.get(p["id"], {}).get("matched", False)
                    and now - self.live.get(p["id"], {}).get("last", 0) <= 1,
                    "cleared": bool(r and p["id"] in r["cleared"])} for p in self.active()]
        current = None
        if r:
            current = {key: copy.deepcopy(r[key]) for key in
                       ("id", "number", "poser_id", "settings", "started_at", "ended_at", "cleared", "outcome")}
            if admin or pid == r["poser_id"] or self.state["phase"] in ("round_result", "final_result"):
                current["pose"] = copy.deepcopy(r["pose"])
            if pid in r["views"] and pid not in r["excluded"]:
                current["target"] = r["views"][pid]["target"]
        # Do not leak other observers' views/angles before the game ends.
        history = [{k: copy.deepcopy(item[k]) for k in
                    ("id", "number", "poser_id", "participants", "elapsed", "outcome", "cleared", "started_at")}
                   for item in self.state["history"]]
        return {"type": "state", "event_id": self.state["id"], "name": self.state["name"],
                "phase": self.state["phase"], "registration_open": self.state["registration_open"],
                "players": players, "round": current, "history": history, "server_time": now,
                "me": pid, "admin": admin, "settings": self.defaults.model_dump() if admin else None}
