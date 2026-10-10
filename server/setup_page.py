"""Separate HTTP onboarding server. It never serves game APIs, credentials, or keys."""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs, urlsplit


def setup_html(https_url, fingerprint, language="ja", allow_admin=True):
    url = escape(https_url, quote=True)
    admin_button = f'<a class="button" href="{url}admin">管理画面を開く</a>' if allow_admin else ''
    fingerprint = escape(fingerprint)
    page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>スマートフォンの初期設定 · Pose Parallax</title>
<style>body{{font-family:system-ui,sans-serif;background:#101827;color:#eef1f6;margin:0;line-height:1.8}}
main{{max-width:680px;margin:auto;padding:30px 22px}}h1{{font-size:28px}}h2{{font-size:20px;margin-top:32px}}
a{{color:#b8f36e}}.button{{display:inline-block;background:#b8f36e;color:#152216;padding:12px 18px;border-radius:10px;text-decoration:none;margin:8px 4px 8px 0}}
li{{margin:12px 0}}code{{overflow-wrap:anywhere;font-size:12px}}.note{{color:#b8c5d7;font-size:14px}}details{{padding:16px;border:1px solid #3c4b60;border-radius:12px;margin-top:20px}}ol{{padding-left:24px}}</style></head>
<body><main><p>POSE PARALLAX</p><nav aria-label="Language"><a href="/?lang=ja">日本語</a> / <a href="/?lang=en">English</a></nav><h1>スマートフォンの初期設定</h1>
<p>カメラを使うため、この会場の証明書を最初の1回だけ登録してください。登録後はHTTPSのゲームページに移動します。</p>
<p class="note">会場の主催者が案内したページであることを確認してから登録してください。端末の設定変更が制限されている場合は主催者にお声がけください。</p>
<h2>iPhone / iPad</h2><ol>
<li>このページをSafariで開き、<a href="/pose-parallax-ca.cer">会場の証明書をダウンロード</a>してプロファイルのダウンロードを許可します。</li>
<li>「設定」→「一般」→「VPNとデバイス管理」から「Pose Parallax Local CA」のプロファイルを選び、インストールします。</li>
<li>「設定」→「一般」→「情報」→「証明書信頼設定」で、その「Pose Parallax Local CA」を<strong>完全に信頼</strong>する設定をオンにします。</li>
<li>Safariに戻り、下の「ゲームを開く」を押します。</li></ol>
<p class="note"><a href="https://support.apple.com/ja-jp/102390" target="_blank" rel="noreferrer">Appleの公式手順</a></p>
<h2>Android</h2><ol>
<li><a href="/pose-parallax-ca.crt">会場の証明書をダウンロード</a>します。</li>
<li>設定から「証明書をインストール」を検索し、<strong>CA証明書</strong>を選び、ダウンロードしたファイルを指定します。端末のPIN等を求められる場合があります。</li>
<li>Chromeを開き直し、下の「ゲームを開く」を押します。</li></ol>
<p class="note">Pixelの例：「セキュリティとプライバシー」→「その他のセキュリティ設定」→「暗号化と認証情報」。名称は機種によって異なります。<a href="https://support.google.com/pixelphone/answer/2844832?hl=ja" target="_blank" rel="noreferrer">Googleの公式手順</a></p>
<a class="button" href="{url}">ゲームを開く</a>{admin_button}
<script>document.querySelector('a.button').hash = location.hash;</script>
<p class="note">登録後も証明書の警告が出る場合は主催者に確認してください。警告を無視して進む方法では、カメラが利用できないことがあります。</p>
<details><summary>主催者との照合・PCでの設定</summary><p>この会場CAのSHA-256指紋です。主催者の起動ログに表示された値と照合できます。</p><code>{fingerprint}</code>
<p>PCで管理画面を使う場合も、この会場CAをOSまたはブラウザの信頼済みルート証明書へ登録してください。配布するのは公開証明書だけです。</p></details>
<details><summary>イベント終了後に削除するには</summary><p>iPhoneでは「VPNとデバイス管理」から該当プロファイルを削除します。Androidでは「信頼できる認証情報」のユーザー項目から該当する「Pose Parallax Local CA」を削除します。</p></details>
</main></body></html>'''
    if language == 'en':
        for ja, en in sorted(SETUP_ENGLISH.items(), key=lambda item: len(item[0]), reverse=True):
            page = page.replace(ja, en)
        page = page.replace('lang="ja"', 'lang="en"').replace('/ja-jp/', '/en-us/').replace('?hl=ja', '?hl=en')
    return page.encode()



SETUP_ENGLISH = {
    "スマートフォンの初期設定": "Phone setup",
    "カメラを使うため、この会場の証明書を最初の1回だけ登録してください。登録後はHTTPSのゲームページに移動します。": "To use your camera, install this venue's certificate once. Then open the HTTPS game page.",
    "会場の主催者が案内したページであることを確認してから登録してください。端末の設定変更が制限されている場合は主催者にお声がけください。": "Confirm that this page was provided by your host before installing. If your device restricts settings changes, ask the host.",
    "このページをSafariで開き、": "Open this page in Safari, ",
    "会場の証明書をダウンロード": "download the venue certificate",
    "してプロファイルのダウンロードを許可します。": ", and allow the profile download.",
    "「設定」→「一般」→「VPNとデバイス管理」から「Pose Parallax Local CA」のプロファイルを選び、インストールします。": "Go to Settings → General → VPN & Device Management. Select the Pose Parallax Local CA profile and install it.",
    "「設定」→「一般」→「情報」→「証明書信頼設定」で、その「Pose Parallax Local CA」を": "Go to Settings → General → About → Certificate Trust Settings and enable ",
    "完全に信頼": "full trust",
    "する設定をオンにします。": " for Pose Parallax Local CA.",
    "Safariに戻り、下の「ゲームを開く」を押します。": "Return to Safari and select Open game below.",
    "Appleの公式手順": "Official Apple instructions",
    "します。": ".",
    "設定から「証明書をインストール」を検索し、": "Search your device settings for Install a certificate. Select ",
    "CA証明書": "CA certificate",
    "を選び、ダウンロードしたファイルを指定します。端末のPIN等を求められる場合があります。": " and choose the downloaded file. You may be asked for your device PIN.",
    "Chromeを開き直し、下の「ゲームを開く」を押します。": "Reopen Chrome and select Open game below.",
    "Pixelの例：「セキュリティとプライバシー」→「その他のセキュリティ設定」→「暗号化と認証情報」。名称は機種によって異なります。": "On Pixel: Security & privacy → More security settings → Encryption & credentials. Labels vary by device. ",
    "Googleの公式手順": "Official Google instructions",
    "ゲームを開く": "Open game",
    "管理画面を開く": "Open admin",
    "登録後も証明書の警告が出る場合は主催者に確認してください。警告を無視して進む方法では、カメラが利用できないことがあります。": "If certificate warnings remain after installation, ask the host. Bypassing a warning may prevent camera access.",
    "主催者との照合・PCでの設定": "Verify with the host / PC setup",
    "この会場CAのSHA-256指紋です。主催者の起動ログに表示された値と照合できます。": "This is the venue CA's SHA-256 fingerprint. Compare it with the value in the host's startup log.",
    "PCで管理画面を使う場合も、この会場CAをOSまたはブラウザの信頼済みルート証明書へ登録してください。配布するのは公開証明書だけです。": "To use the admin page on a PC, install this venue CA in your OS or browser's trusted root certificates. Only the public certificate is distributed.",
    "イベント終了後に削除するには": "Remove after the event",
    "iPhoneでは「VPNとデバイス管理」から該当プロファイルを削除します。Androidでは「信頼できる認証情報」のユーザー項目から該当する「Pose Parallax Local CA」を削除します。": "On iPhone, remove the profile from VPN & Device Management. On Android, remove Pose Parallax Local CA from the User section of Trusted credentials.",
}


def create_setup_server(host, port, https_url, tls, allow_admin=True):
    pages = {language: setup_html(https_url, tls.fingerprint, language, allow_admin) for language in ("ja", "en")}
    certificate = tls.ca_der

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ("/", "/setup", "/admin"):
                language = parse_qs(urlsplit(self.path).query).get("lang", ["ja"])[0]
                self.respond(200, pages.get(language, pages["ja"]), "text/html; charset=utf-8")
            elif path in ("/pose-parallax-ca.crt", "/pose-parallax-ca.cer"):
                self.respond(200, certificate, "application/x-x509-ca-cert", path[1:])
            elif path == "/health":
                self.respond(200, b'{"status":"ok"}', "application/json")
            elif path.startswith("/api/") or path == "/ws":
                self.respond(426, b'{"detail":"Use the HTTPS game URL"}', "application/json")
            else:
                self.respond(404, b"Not found", "text/plain")

        def respond(self, status, body, content_type, filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="certificate-setup")
    thread.start()
    return server
