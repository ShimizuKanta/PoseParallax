# Windowsアプリ

Windows 10 / 11 x64向けのサーバーアプリです。参加者はスマートフォンのブラウザで接続します。

## 利用者の操作（標準：証明書不要）

1. `PoseParallax-Setup-0.4.0-windows-x64.exe` を実行し、インストールします。
2. デスクトップまたはスタートメニューの **Pose Parallax** を開きます。「インターネット（証明書不要）」で自動起動します。
3. 「稼働中」になったら表示されたQRを参加者に案内します。公開HTTPSの接続確認が完了するまでQRは表示されません。
4. 参加者はスマートフォンでQRを読み、名前を入力してカメラを許可します。Cloudflareアカウント・CA証明書登録・専用スマートフォンアプリは不要です。
5. 主催者は「管理者パスワードをコピー」→「管理画面を開く」でログインします。管理画面はこのPCのローカルURLで開き、その画面の参加QRには公開HTTPS URLが反映されます。
6. プレイ中はアプリを開いたままにします。「サーバー停止」またはウィンドウを閉じる操作で確認後に停止します。

PCとスマートフォンにはプレイ中もインターネット接続が必要です。同じWi-Fiに接続する必要はありません。接続し直すたびに参加URLが変わり、アプリと管理画面のQRへ新しいURLを自動反映します。古いQRは使えないので新しいQRを案内してください。ホスト名が変わるため、参加者のブラウザのログイン状態も新しいURLへは引き継がれません。

サーバーはPC内部の空きポートで待ち受け、同梱のCloudflare Quick Tunnelが公開HTTPSへ中継します。参加用の受信ポート開放は不要です。ネットワークがトンネルの外向き接続を制限している場合は接続できません。接続開始のタイムアウトやトンネルプロセスの終了は画面に表示し、QRを消します。環境を確認して「サーバー起動」で再試行してください。トンネル内の一時的な通信断はcloudflaredが再接続を試みます。

ゲーム処理と結果保存はPCで行います。画面・モデル・表示名・姿勢の33点の座標・スコア・結果の通信はCloudflareを経由します。カメラ映像は端末内で処理し送信しません。公開URLの管理画面からログインする場合はパスワードとセッション情報も中継されます。このPCの「管理画面を開く」は外部を経由しません。

Quick Tunnelは試用・開発向けで、稼働保証がありません。本番の固定URL運用には通常のCloudflare Tunnel等を別途検討してください。[公式の条件](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

## 言語・詳細画面

起動画面の右上から「日本語 / English」を選びます。選択は保存し、次回の起動でも適用します。言語切り替えでサーバーやQRは作り直しません。「管理画面を開く」「証明書の設定手順」は選択した言語で開きます。参加者は自分のブラウザで言語を選べます。

通常表示は稼働状態・QR・参加URL・管理画面・パスワードコピー・起動停止を中心にしています。「詳細」から接続方式、証明書手順、通信の説明、保存フォルダーとログを確認できます。詳細画面を閉じてもサーバーは動き続けます。ゲーム画面の操作は [画面と言語](UI_Guide.md) を参照してください。

## インターネットを使わない会場LAN接続

「詳細」を開き、停止中に「会場LAN（証明書登録が必要）」を選び、「サーバー起動」を押します。従来どおりLAN IPを自動検出し、HTTPS証明書と証明書設定ページを生成します。

- PCと参加端末を同じLANに接続し、Windowsファイアウォールで受信TCP 8000・8443を許可します。
- 「詳細」の「証明書の設定手順」から会場CAをダウンロードし、主催者PCとスマートフォンへ登録します。
- 最初は「初回の証明書設定」QR、登録後は「ゲーム参加」QRを使います。

アプリにはPython・画面・モデル・cloudflaredを同梱するため、利用者によるPython・Node.js・OpenSSL・cloudflaredの個別インストールは不要です。

## 保存先と更新

- インストール先：`%LOCALAPPDATA%\Programs\PoseParallax`
- 保存先：`%LOCALAPPDATA%\PoseParallax`（`POSE_DATA_DIR` 環境変数で変更可能）
- `pose.sqlite3`：参加者・設定・結果
- `admin-password.txt`：管理者パスワード
- `tls\`：会場CAとサーバー証明書。秘密鍵は配布しないでください。
- `ui-preferences.json`：起動画面の言語
- `desktop.log`：起動・停止・障害ログ（ローテーションあり）

更新前にアプリを終了して、新しいインストーラーを実行します。更新・アンインストールでも保存先は削除しません。バックアップはサーバーを停止して保存フォルダー全体をコピーします。同じCAを保持すれば、IP変更時もスマートフォンのCA再登録は不要です。旧サーバーから移す場合も停止後に旧 `data` の内容を保存先へコピーできます。同じ保存先でアプリを二重起動すると、2つ目は起動を中止します。

未署名のビルドではWindowsのSmartScreen警告が出る場合があります。一般配布の際は配布者の証明書でEXE・インストーラーへコード署名してください。

## 開発者：Windowsで配布物を作る

必要：Windows x64、Python 3.12（Tkを含む標準インストール）、Node.js 22.12以上の22系、Inno Setup 6。OpenSSLコマンドは不要です。依存取得時にはインターネット接続が必要です。

PowerShellでプロジェクト直下から実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
```

スクリプトがWindows専用仮想環境 `.venv-windows` を作り、依存取得、公式cloudflaredの取得・SHA-256検証、モデル取得、画面ビルド、PyInstallerでのEXE生成、Inno Setupでのインストーラー生成を行います。実行ポリシーの指定はこのプロセスだけに適用されます。

出力：

- `release\PoseParallax\`：ポータブル版。**フォルダー全体**を配布し、`PoseParallax.exe` を起動します。
- `release\PoseParallax-Setup-0.4.0-windows-x64.exe`：インストーラー。

バージョンは `packaging/windows/installer.iss` の `AppVersion` で指定します。

`feat/windows-desktop-app` ブランチをGitHubへpushすると、Actionsの **Build Windows app** が実行されます。default branchにもworkflowを追加した後は手動実行も可能です。Windows runnerでテストと同梱EXEのHTTPS・アセット配信・停止を検証し、成功時に配布物をartifactとして保存します。公開リリースへの自動投稿はしません。

## 検証

```powershell
.\.venv-windows\Scripts\python.exe -m pytest -q tests/test_desktop.py tests/test_tunnel.py
.\.venv-windows\Scripts\python.exe -m desktop.entry
```

配布EXEには隔離データ・ループバック・空きポートで動作するスモークテストもあります。

```powershell
$p = Start-Process .\release\PoseParallax\PoseParallax.exe -ArgumentList '--smoke-test', 'C:\Temp\PoseParallaxSmoke' -PassThru -Wait
Get-Content C:\Temp\PoseParallaxSmoke\smoke-result.json
```

実際の公開HTTPS・参加・Secure Cookie・WebSocketの確認は `--smoke-test` を `--tunnel-smoke-test` に置き換えます。隔離データを使うため通常のゲームデータは変更しません。

`{"ok": true}` が成功です。Windowsインストーラーの実行、GUIの操作、ファイアウォール越しのiPhone / Android接続はWindows実機で確認してください。Linuxでのテスト成功だけではWindows配布物の動作確認にはなりません。

## 構成

`desktop/gui.py` がTkの操作画面、`desktop/runtime.py` がサーバーのライフサイクル、`desktop/certificates.py` が外部コマンド不要の証明書生成です。ゲームとAPIは既存の `server` を共有します。`desktop/tunnel.py` がcloudflaredの子プロセス、URL取得、公開HTTPSの確認、終了を管理します。PyInstallerは静的画面・モデル・WASM・Python依存とcloudflaredを同梱します。バージョンとハッシュは `packaging/cloudflared.json` に固定し、ビルド時のみ取得します。Apacheライセンスも同梱します。

参考：[PyInstallerの配布方式](https://pyinstaller.org/en/stable/operating-mode.html)、[cryptographyのX.509 API](https://cryptography.io/en/stable/x509/)、[Inno Setupのユーザー単位インストール](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)。WindowsのEXEはWindows上でビルドします。
