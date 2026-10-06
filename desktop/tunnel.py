"""Own one Quick Tunnel process and wait for its public HTTPS endpoint."""
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

URL = re.compile(r'https://([a-z0-9-]+\.trycloudflare\.com)(?=[\s"/]|$)', re.I)


def executable_path():
    name = 'cloudflared.exe' if os.name == 'nt' else 'cloudflared'
    root = Path(__file__).resolve().parent.parent
    for candidate in (root / 'cloudflared' / name, root / 'vendor/cloudflared' / name):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError('接続用ツールが見つかりません。アプリを再インストールしてください。')


class QuickTunnel:
    def __init__(self, executable=None, timeout=90):
        self.executable, self.timeout = executable, timeout
        self.process = self.reader = self.temporary = None
        self.url = None
        self.connected = threading.Event()

    def _read(self):
        for line in self.process.stdout:
            logging.info('cloudflared: %s', line.rstrip())
            match = URL.search(line)
            if match:
                self.url = 'https://' + match.group(1).lower() + '/'
            if 'Registered tunnel connection' in line:
                self.connected.set()

    def start(self, origin, stop_requested):
        if stop_requested.is_set():
            return None
        self.temporary = tempfile.TemporaryDirectory(prefix='pose-tunnel-')
        config = Path(self.temporary.name) / 'config.yml'
        # Personal cloudflared configurations must not affect the app's Quick Tunnel.
        config.write_text('{}\n', encoding='utf-8')
        self.process = subprocess.Popen([
            self.executable or executable_path(), '--config', str(config), 'tunnel',
            '--no-autoupdate', '--url', origin, '--protocol', 'http2', '--output', 'json',
            '--metrics', '127.0.0.1:0', '--loglevel', 'info', '--grace-period', '1s',
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
           encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL,
           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
           env={key: value for key, value in os.environ.items()
                if not key.startswith(('TUNNEL_', 'CLOUDFLARED_'))})
        self.reader = threading.Thread(target=self._read, daemon=True, name='cloudflared-log')
        self.reader.start()
        deadline = time.monotonic() + self.timeout
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            if stop_requested.is_set():
                return None
            if self.process.poll() is not None:
                raise RuntimeError('インターネット接続を開始できませんでした。接続環境を確認して再試行してください。')
            if self.url and self.connected.is_set():
                try:
                    with opener.open(self.url + 'api/health', timeout=3) as response:
                        if response.status == 200 and response.read(1024).strip() == b'{"status":"ok"}':
                            return self.url
                except (OSError, urllib.error.URLError):
                    pass
            stop_requested.wait(.2)
        raise RuntimeError('インターネット接続がタイムアウトしました。接続環境を確認して再試行してください。')

    def poll(self):
        return self.process.poll() if self.process else None

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=5)
            if self.reader:
                self.reader.join(timeout=2)
            self.process.stdout.close()
        if self.temporary:
            self.temporary.cleanup()
