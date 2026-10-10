"""Bound registration attempts without blocking a shared-Wi-Fi group of 50."""
from collections import OrderedDict, deque
import hashlib
import hmac
import secrets
import time
from fastapi.responses import JSONResponse


class RequestBodyLimit:
    """Bound streamed bodies before JSON parsing, including chunked requests."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > 16 * 1024:
                return await JSONResponse({'detail': '送信データが大きすぎます。'}, status_code=413)(scope, receive, send)
            body.extend(chunk)
            if not message.get('more_body', False):
                break

        async def replay():
            nonlocal body
            if body is not None:
                payload, body = bytes(body), None
                return {'type': 'http.request', 'body': payload, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)


class RegistrationGuard:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.key = secrets.token_bytes(32)
        self.buckets = OrderedDict()

    def cookie(self):
        nonce = secrets.token_urlsafe(18)
        return nonce + "." + hmac.new(self.key, nonce.encode(), hashlib.sha256).hexdigest()

    def identity(self, cookie):
        if not cookie or len(cookie) > 128 or "." not in cookie:
            return None
        nonce, signature = cookie.rsplit(".", 1)
        expected = hmac.new(self.key, nonce.encode(), hashlib.sha256).hexdigest()
        return nonce if hmac.compare_digest(signature.encode(), expected.encode()) else None

    def allow(self, ip, cookie):
        now = self.clock()
        for key in list(self.buckets):
            bucket = self.buckets[key]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if not bucket:
                del self.buckets[key]
        keys = [("global", 120), ("ip:" + ip, 60)]
        identity = self.identity(cookie)
        if identity:
            keys.append(("browser:" + identity, 3))
        allowed = all(len(self.buckets.get(key, ())) < limit for key, limit in keys)
        for key, limit in keys:
            bucket = self.buckets.setdefault(key, deque())
            if len(bucket) < limit:
                bucket.append(now)
            self.buckets.move_to_end(key)
        while len(self.buckets) > 2048:
            self.buckets.popitem(last=False)
        return allowed
