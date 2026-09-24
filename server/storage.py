import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, role TEXT NOT NULL,
                player_id TEXT, expires REAL NOT NULL);
        """)

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM documents WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO documents VALUES (?, ?)", (key, json.dumps(value)))

    def session(self, role, player_id=None):
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            self.db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                            (hashlib.sha256(token.encode()).hexdigest(), role, player_id, time.time() + 86400))
        return token

    def auth(self, token):
        if not token:
            return None
        row = self.db.execute("SELECT role, player_id FROM sessions WHERE token_hash=? AND expires>?",
                              (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return {"role": row[0], "player_id": row[1]} if row else None

    def revoke(self, token):
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def close(self):
        self.db.close()
