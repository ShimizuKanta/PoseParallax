"""Runs the existing app with graceful shutdown, outside the GUI thread."""
import asyncio
import ipaddress
import os
from pathlib import Path
import socket
import threading

import uvicorn
from server.network import detect_lan_ip
from server.setup_page import create_setup_server
from .certificates import ensure_tls


def data_directory():
    if os.environ.get('POSE_DATA_DIR'):
        return Path(os.environ['POSE_DATA_DIR']).expanduser().resolve()
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'PoseParallax'


class InstanceLock:
    """OS-held lock; an abnormal exit releases it automatically."""
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.stream = (directory / 'desktop.lock').open('a+b')
        self.stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not self.stream.read(1):
                self.stream.write(b'0'); self.stream.flush()
            self.stream.seek(0)
            try:
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.stream.close()
                raise RuntimeError('この保存先を使うアプリはすでに起動しています。') from None
        else:
            import fcntl
            try:
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.stream.close()
                raise RuntimeError('この保存先を使うアプリはすでに起動しています。') from None

    def close(self):
        self.stream.close()


class Runtime:
    def __init__(self, directory, notify, host='0.0.0.0', port=8443, setup_port=8000, address=None):
        self.directory, self.notify = Path(directory), notify
        self.host, self.port, self.setup_port, self.address = host, port, setup_port, address
        self.stop_requested = threading.Event()

    def stop(self):
        self.stop_requested.set()

    def run(self):
        listener, setup = None, None
        previous = {key: os.environ.get(key) for key in ('POSE_DATA_DIR', 'POSE_LAN_IP', 'POSE_SETUP_URL', 'POSE_PUBLIC_URL')}
        try:
            address = self.address or detect_lan_ip()
            if not address:
                raise RuntimeError('LAN IPを検出できません。Wi-Fi / LANに接続して再試行してください。')
            tls = ensure_tls(self.directory / 'tls', address)
            if self.stop_requested.is_set():
                return
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Windows must not allow a second process to reuse this listening port.
            if os.name == 'nt':
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((self.host, self.port))
            listener.listen(128)
            listener.setblocking(False)
            url = f'https://{address}:{listener.getsockname()[1]}/'
            setup = create_setup_server(self.host, self.setup_port, url, tls)
            setup_url = f'http://{address}:{setup.server_port}/'
            os.environ.update(POSE_DATA_DIR=str(self.directory), POSE_SETUP_URL=setup_url, POSE_PUBLIC_URL=url)
            if not ipaddress.ip_address(address).is_loopback:
                os.environ['POSE_LAN_IP'] = address
            else:
                os.environ.pop('POSE_LAN_IP', None)
            from server.app import create_app
            server = uvicorn.Server(uvicorn.Config(create_app(self.directory), host=self.host,
                port=self.port, ssl_certfile=str(tls.cert), ssl_keyfile=str(tls.key),
                loop='asyncio', http='h11', ws='websockets', log_config=None,
                ws_max_size=8192, timeout_graceful_shutdown=5))

            async def serve():
                async def guarded_serve():
                    try:
                        await server.serve(sockets=[listener])
                    except SystemExit as exc:
                        raise RuntimeError('サーバー初期化に失敗しました。ログを確認してください。') from exc
                task = asyncio.create_task(guarded_serve())
                announced = False
                try:
                    while not task.done():
                        if self.stop_requested.is_set():
                            server.should_exit = True
                        if server.started and not announced and not self.stop_requested.is_set():
                            self.notify('ready', {'url': url, 'setup_url': setup_url, 'fingerprint': tls.fingerprint})
                            announced = True
                        await asyncio.sleep(.1)
                    await task
                    if not announced and not self.stop_requested.is_set():
                        raise RuntimeError('サーバーを起動できませんでした。ログを確認してください。')
                finally:
                    if not task.done():
                        server.should_exit = True
                        await task
            asyncio.run(serve())
        except (Exception, SystemExit) as exc:
            import logging
            logging.exception('Desktop server failed')
            self.notify('error', str(exc))
        finally:
            if setup:
                setup.shutdown(); setup.server_close()
            if listener:
                listener.close()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            self.notify('stopped', None)
