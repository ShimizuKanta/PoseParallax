"""Checks the actual installed bundle, including HTTPS and static assets."""
import asyncio
import http.cookiejar
import json
import logging
import os
import subprocess
from pathlib import Path
import queue
import ssl
import threading
import urllib.request
from urllib.parse import urlsplit, urlunsplit, parse_qs

from .runtime import Runtime, InstanceLock


def run(destination, mode='lan'):
    directory = Path(destination).resolve()
    lock = InstanceLock(directory)
    logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(directory / 'smoke.log', encoding='utf-8')], force=True)
    events = queue.Queue()
    runtime = Runtime(directory, lambda *event: events.put(event), host='127.0.0.1',
                      address='127.0.0.1', port=0, setup_port=0, mode=mode)
    worker = threading.Thread(target=runtime.run)
    result = {'ok': False}
    worker.start()
    try:
        from .tunnel import executable_path
        subprocess.run([executable_path(), '--version'], check=True, capture_output=True, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        while True:
            kind, details = events.get(timeout=110)
            if kind == 'progress':
                continue
            if kind != 'ready':
                raise RuntimeError(str(details))
            break
        context = ssl.create_default_context(cafile=str(directory / 'tls/root-ca.pem') if mode == 'lan' else None)
        # Ignore system proxy settings for this local-only packaging test.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        parsed = urlsplit(details['url'])
        origin = urlunsplit(parsed._replace(fragment=''))
        invite = parse_qs(parsed.fragment)['invite'][0]
        for path in ('api/health', '', 'inference-worker.js', 'models/pose_landmarker_lite.task',
                     'licenses/npm/three/LICENSE', 'licenses/mediapipe/LICENSE', 'licenses/PoseParallax-LICENSE'):
            with opener.open(origin + path, timeout=10) as response:
                if response.status != 200 or not response.read(1):
                    raise RuntimeError('Invalid bundled response: ' + path)
        with opener.open(details['admin_url'], timeout=10) as response:
            assert response.status == 200
        try:
            opener.open(origin + 'admin', timeout=10)
            raise RuntimeError('Public admin route must be blocked')
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        if mode == 'lan':
            with opener.open(details['setup_url'].split('#')[0] + 'pose-parallax-ca.cer', timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError('Certificate onboarding failed')
        else:
            with opener.open(origin + 'api/state', timeout=10) as response:
                state = json.load(response)
                assert state['join_url'] is None and state['players'] == []
            cookies = http.cookiejar.CookieJar()
            opener.add_handler(urllib.request.HTTPCookieProcessor(cookies))
            request = urllib.request.Request(origin + 'api/join', data=json.dumps({'name':'Smoke test','invite_token':invite}).encode(),
                headers={'Content-Type': 'application/json', 'Origin': origin.rstrip('/')})
            with opener.open(request, timeout=10) as response:
                assert response.status == 200
            assert any(cookie.secure for cookie in cookies)
            async def websocket_check():
                import websockets
                async with websockets.connect(origin.replace('https://', 'wss://') + 'ws',
                    origin=origin.rstrip('/'),
                    additional_headers={'Cookie': '; '.join(f'{c.name}={c.value}' for c in cookies)},
                    open_timeout=15) as ws:
                    assert json.loads(await asyncio.wait_for(ws.recv(), 10))['type'] == 'state'
            asyncio.run(websocket_check())
        result = {'ok': True}
    except Exception as exc:
        result = {'ok': False, 'error': str(exc)}
    finally:
        runtime.stop(); worker.join(timeout=15)
        if worker.is_alive():
            result = {'ok': False, 'error': 'Server failed to stop'}
        (directory / 'smoke-result.json').write_text(json.dumps(result), encoding='utf-8')
        lock.close()
    if not result['ok']:
        raise RuntimeError(result)
