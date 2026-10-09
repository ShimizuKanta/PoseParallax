"""Desktop UI translations and per-install language preference."""
import json
from pathlib import Path
import tkinter as tk
import weakref

ENGLISH = {
    'Pose Parallax — サーバー': 'Pose Parallax — Server',
    '起動準備中…': 'Preparing to start…',
    'サーバーを起動しています…': 'Starting server…',
    '参加用のHTTPS URLを取得しています…': 'Getting the HTTPS join URL…',
    '稼働中 — このウィンドウを開いたままにしてください。': 'Running — Keep this window open.',
    '停止しています…': 'Stopping…',
    '停止しました。': 'Stopped.',
    '管理画面を開く': 'Open admin',
    'URLをコピー': 'Copy URL',
    '管理者パスワードをコピー': 'Copy admin password',
    'サーバー起動': 'Start server',
    'サーバー停止': 'Stop server',
    '詳細': 'Details',
    '閉じる': 'Close',
    '接続方式': 'Connection method',
    'インターネット（証明書不要）': 'Internet (no certificate setup)',
    '会場LAN（証明書登録が必要）': 'Venue LAN (certificate setup required)',
    '初回の証明書設定': 'First-time certificate setup',
    'ゲーム参加': 'Join game',
    '証明書の設定手順': 'Certificate instructions',
    '保存フォルダー・ログを開く': 'Open data folder / logs',
    'QRを読み、名前を入力してカメラを許可すれば参加できます。': 'Scan the QR, enter a name and allow camera access to join.',
    'PCとスマートフォンはプレイ中もインターネット接続が必要です。': 'The PC and phones need internet access throughout the game.',
    '接続し直すとURLが変わります。新しいQRを案内してください。': 'Restarting changes the URL. Share the new QR code.',
    'PCとスマートフォンを同じLANに接続してください。': 'Connect the PC and phones to the same LAN.',
    '初回は各端末で証明書を登録します。Windowsのファイアウォールは': 'Install the certificate once on each device. In Windows Firewall,',
    'プライベートネットワークでTCP 8000・8443の接続を許可してください。': 'allow TCP ports 8000 and 8443 on private networks.',
    '画面・表示名・姿勢の座標・結果の通信はCloudflareを経由します。': 'Pages, display names, pose coordinates and results pass through Cloudflare.',
    'カメラ映像は送信しません。Quick Tunnelは稼働保証のない試用サービスです。': 'Camera images are never uploaded. Quick Tunnel is a trial service without an uptime guarantee.',
    'プレイ中の接続が切れます。サーバーを停止しますか？': 'Players will be disconnected. Stop the server?',
    '終了': 'Exit',
    'サーバーを停止してアプリを終了しますか？': 'Stop the server and exit?',
    '管理者パスワード': 'Admin password',
    'クリップボードにコピーしました。管理画面へ貼り付けてください。': 'Copied to the clipboard. Paste it into the admin page.',
    'サーバーの起動後にもう一度お試しください。': 'Try again after the server starts.',
    '保存フォルダーの desktop.log を確認してください。': 'Check desktop.log in the data folder.',
    'この保存先を使うアプリはすでに起動しています。': 'An app using this data folder is already running.',
    'LAN IPを検出できません。Wi-Fi / LANに接続して再試行してください。': 'Cannot detect the LAN IP. Connect to Wi-Fi / LAN and retry.',
    'サーバー初期化に失敗しました。ログを確認してください。': 'Server initialization failed. Check the log.',
    'インターネット接続が終了しました。「サーバー起動」で接続し直してください。': 'Internet connection ended. Select Start server to reconnect.',
    'サーバーを起動できませんでした。ログを確認してください。': 'Could not start the server. Check the log.',
    '接続用ツールが見つかりません。アプリを再インストールしてください。': 'Connection tool missing. Please reinstall the app.',
    'インターネット接続を開始できませんでした。接続環境を確認して再試行してください。': 'Could not start the internet connection. Check your network and retry.',
    'インターネット接続がタイムアウトしました。接続環境を確認して再試行してください。': 'Internet connection timed out. Check your network and retry.',
}


class LocalizedVar(tk.StringVar):
    def __init__(self, translator, value=''):
        self.translator = weakref.proxy(translator)
        self.source = value
        super().__init__(value=translator.text(value))
        translator.variables.append(weakref.ref(self))

    def set(self, value):
        self.source = value
        super().set(self.translator.text(value))

    def refresh(self):
        super().set(self.translator.text(self.source))


class Translator:
    def __init__(self, directory):
        self.path = Path(directory) / 'ui-preferences.json'
        self.language = 'ja'
        try:
            if json.loads(self.path.read_text()).get('language') == 'en':
                self.language = 'en'
        except (OSError, ValueError, AttributeError):
            pass
        self.widgets, self.variables = [], []

    def text(self, source):
        if self.language == 'ja':
            return source
        lines = []
        for line in source.split('\n'):
            if line.startswith('起動・動作エラー: '):
                lines.append('Startup / runtime error: ' + self.text(line[len('起動・動作エラー: '):]))
            elif line.startswith('会場CA SHA-256: '):
                lines.append('Venue CA SHA-256: ' + line[len('会場CA SHA-256: '):])
            else:
                lines.append(ENGLISH.get(line, line))
        return '\n'.join(lines)

    def bind(self, widget, source):
        self.widgets.append((widget, source))
        widget.configure(text=self.text(source))
        return widget

    def select(self, language):
        self.language = 'en' if language == 'en' else 'ja'
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'language': self.language}), encoding='utf-8')
        except OSError:
            pass
        for widget, source in self.widgets:
            widget.configure(text=self.text(source))
        for reference in self.variables:
            variable = reference()
            if variable is not None:
                variable.refresh()
