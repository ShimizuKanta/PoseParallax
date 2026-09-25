# Windowsアプリ

Windows 10 / 11 x64向けのサーバーアプリです。参加者は同じLANのスマートフォンからブラウザで接続します。

## 利用者の操作

1. `PoseParallax-Setup-0.1.0-windows-x64.exe` を実行し、インストールします。
2. デスクトップまたはスタートメニューの **Pose Parallax** を開きます。HTTPSサーバーが自動起動します。
3. Windowsファイアウォールの確認が出た場合は、会場のプライベートネットワークで許可します。接続できない場合は受信TCP 8000・8443の許可を確認してください。
4. 「このPCの証明書設定」から公開CA証明書をダウンロードし、Windowsの「現在のユーザー → 信頼されたルート証明機関」に登録します。アプリはOSの証明書ストアを自動変更しません。
5. 「管理者パスワードをコピー」→「管理画面を開く」でログインします。
6. 初参加のスマートフォンでは「初回の証明書設定」QRを読み取り、案内に従いCAを登録します。登録済みの端末には「ゲーム参加」QRを案内します。
7. プレイ中はアプリを開いたままにします。「サーバー停止」またはウィンドウを閉じる操作で確認後に停止します。進行中のラウンドは再起動時に中止として復元されます。

利用者によるPython・Node.js・OpenSSLのインストールは不要です。モデルも同梱され、初回起動時のダウンロードはありません。IPは起動のたびに検出します。ネットワークを変えた場合は停止して起動し直してください。

## 保存先と更新

- インストール先：`%LOCALAPPDATA%\Programs\PoseParallax`
- 保存先：`%LOCALAPPDATA%\PoseParallax`（`POSE_DATA_DIR` 環境変数で変更可能）
- `pose.sqlite3`：参加者・設定・結果
- `admin-password.txt`：管理者パスワード
- `tls\`：会場CAとサーバー証明書。秘密鍵は配布しないでください。
- `desktop.log`：起動・停止・障害ログ（ローテーションあり）

更新前にアプリを終了して、新しいインストーラーを実行します。更新・アンインストールでも保存先は削除しません。バックアップはサーバーを停止して保存フォルダー全体をコピーします。同じCAを保持すれば、IP変更時もスマートフォンのCA再登録は不要です。旧サーバーから移す場合も停止後に旧 `data` の内容を保存先へコピーできます。同じ保存先でアプリを二重起動すると、2つ目は起動を中止します。

未署名のビルドではWindowsのSmartScreen警告が出る場合があります。一般配布の際は配布者の証明書でEXE・インストーラーへコード署名してください。

## 開発者：Windowsで配布物を作る

必要：Windows x64、Python 3.12（Tkを含む標準インストール）、Node.js 22.12以上の22系、Inno Setup 6。OpenSSLコマンドは不要です。依存取得時にはインターネット接続が必要です。

PowerShellでプロジェクト直下から実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
```

スクリプトがWindows専用仮想環境 `.venv-windows` を作り、依存取得、モデル取得、画面ビルド、PyInstallerでのEXE生成、Inno Setupでのインストーラー生成を行います。実行ポリシーの指定はこのプロセスだけに適用されます。

出力：

- `release\PoseParallax\`：ポータブル版。**フォルダー全体**を配布し、`PoseParallax.exe` を起動します。
- `release\PoseParallax-Setup-0.1.0-windows-x64.exe`：インストーラー。

バージョンは `packaging/windows/installer.iss` の `AppVersion` で指定します。

`feat/windows-desktop-app` ブランチをGitHubへpushすると、Actionsの **Build Windows app** が実行されます。default branchにもworkflowを追加した後は手動実行も可能です。Windows runnerでテストと同梱EXEのHTTPS・アセット配信・停止を検証し、成功時に配布物をartifactとして保存します。公開リリースへの自動投稿はしません。

## 検証

```powershell
.\.venv-windows\Scripts\python.exe -m pytest -q tests/test_desktop.py
.\.venv-windows\Scripts\python.exe -m desktop.entry
```

配布EXEには隔離データ・ループバック・空きポートで動作するスモークテストもあります。

```powershell
$p = Start-Process .\release\PoseParallax\PoseParallax.exe -ArgumentList '--smoke-test', 'C:\Temp\PoseParallaxSmoke' -PassThru -Wait
Get-Content C:\Temp\PoseParallaxSmoke\smoke-result.json
```

`{"ok": true}` が成功です。Windowsインストーラーの実行、GUIの操作、ファイアウォール越しのiPhone / Android接続はWindows実機で確認してください。Linuxでのテスト成功だけではWindows配布物の動作確認にはなりません。

## 構成

`desktop/gui.py` がTkの操作画面、`desktop/runtime.py` がサーバーのライフサイクル、`desktop/certificates.py` が外部コマンド不要の証明書生成です。ゲームとAPIは既存の `server` を共有します。PyInstallerは静的画面・モデル・WASMとPython依存を同梱します。

参考：[PyInstallerの配布方式](https://pyinstaller.org/en/stable/operating-mode.html)、[cryptographyのX.509 API](https://cryptography.io/en/stable/x509/)、[Inno Setupのユーザー単位インストール](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)。WindowsのEXEはWindows上でビルドします。
