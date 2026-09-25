"""Checks the actual installed bundle, including HTTPS and static assets."""
import json
from pathlib import Path
import queue
import ssl
import threading
import urllib.request

from .runtime import Runtime, InstanceLock


def run(destination):
    directory = Path(destination).resolve()
    lock = InstanceLock(directory)
    events = queue.Queue()
    runtime = Runtime(directory, lambda *event: events.put(event), host='127.0.0.1',
                      address='127.0.0.1', port=0, setup_port=0)
    worker = threading.Thread(target=runtime.run)
    result = {'ok': False}
    worker.start()
    try:
        kind, details = events.get(timeout=45)
        if kind != 'ready':
            raise RuntimeError(str(details))
        context = ssl.create_default_context(cafile=str(directory / 'tls/root-ca.pem'))
        # Ignore system proxy settings for this local-only packaging test.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        for path in ('api/health', '', 'admin', 'inference-worker.js', 'models/pose_landmarker_lite.task'):
            with opener.open(details['url'] + path, timeout=10) as response:
                if response.status != 200 or not response.read(1):
                    raise RuntimeError('Invalid bundled response: ' + path)
        with opener.open(details['setup_url'] + 'pose-parallax-ca.cer', timeout=10) as response:
            if response.status != 200:
                raise RuntimeError('Certificate onboarding failed')
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
