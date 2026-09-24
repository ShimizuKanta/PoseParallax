"""Start HTTPS on the LAN, plus an HTTP certificate onboarding page."""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit
import uvicorn
from .network import configured_public_url, detect_lan_ip, join_url
from .setup_page import create_setup_server
from .tls import ensure_local_tls


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start Pose Parallax with LAN HTTPS")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: all IPv4 interfaces)")
    parser.add_argument("--port", type=int, help="HTTPS port (default: 8443; HTTP mode: 8000)")
    parser.add_argument("--http", action="store_true", help="HTTP-only development mode; phone cameras require HTTPS")
    parser.add_argument("--setup-port", type=int, default=8000, help="HTTP certificate setup port; 0 disables it")
    parser.add_argument("--ssl-certfile")
    parser.add_argument("--ssl-keyfile")
    args = parser.parse_args(argv)
    try:
        port = args.port if args.port is not None else int(os.environ.get("POSE_PORT", "8000" if args.http else "8443"))
    except ValueError:
        parser.error("POSE_PORT must be a port number")
    if not 1 <= port <= 65535 or not 0 <= args.setup_port <= 65535:
        parser.error("invalid port number")
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        parser.error("provide both --ssl-certfile and --ssl-keyfile")
    if args.http and args.ssl_certfile:
        parser.error("--http cannot be combined with SSL certificate options")
    local_tls = not args.http and not args.ssl_certfile
    if local_tls and args.setup_port == port:
        parser.error("HTTPS and certificate setup ports must be different")
    try:
        lan_ip = detect_lan_ip()
        public_url = configured_public_url()
        if not args.http and public_url and urlsplit(public_url).scheme != "https":
            raise ValueError("HTTPS起動時のPOSE_PUBLIC_URLにはhttps://を指定してください。")
    except ValueError as exc:
        parser.error(str(exc))
    if lan_ip:
        os.environ["POSE_LAN_IP"] = lan_ip
    scheme = "http" if args.http else "https"
    host = f"[{args.host}]" if ":" in args.host else args.host
    url = join_url(f"{scheme}://{host}:{port}/", lan_ip, public_url)
    if not url:
        parser.error("LAN IPを検出できません。POSE_LAN_IP または POSE_PUBLIC_URL を指定してください。")
    cert, key = args.ssl_certfile, args.ssl_keyfile
    setup_server = None
    os.environ.pop("POSE_SETUP_URL", None)
    try:
        if local_tls:
            data_dir = Path(os.environ.get("POSE_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
            tls = ensure_local_tls(data_dir / "tls", lan_ip, urlsplit(url).hostname)
            cert, key = str(tls.cert), str(tls.key)
            print(f"会場CA SHA-256: {tls.fingerprint}", flush=True)
            if args.setup_port:
                setup_url = join_url(f"http://{host}:{args.setup_port}/", lan_ip)
                if setup_url is None:
                    raise ValueError("証明書配布用のLAN IPを検出できません。POSE_LAN_IPを指定してください。")
                setup_server = create_setup_server(args.host, args.setup_port, url, tls)
                os.environ["POSE_SETUP_URL"] = setup_url
                print(f"スマートフォンの初期設定: {setup_url}", flush=True)
            print("各端末で会場CAを1回だけ登録・信頼してから、HTTPSページを開いてください。", flush=True)
        print(f"\n参加URL: {url}\n管理画面: {url}admin\n", flush=True)
        uvicorn.run("server.app:app", host=args.host, port=port, workers=1, ws_max_size=8192,
                    ssl_certfile=cert, ssl_keyfile=key, timeout_graceful_shutdown=5)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if setup_server:
            setup_server.shutdown()
            setup_server.server_close()


if __name__ == "__main__":
    main()
