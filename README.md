# Codex Goal Monitor

[![Build](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml/badge.svg)](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml)

CodexのCapacityエラーや通信切断から作業を自動再開し、Discordへ通知する、Rust製の常駐アプリです。

- **Windows・macOS・Linuxに対応**。通常のターミナルとtmuxの両方を監視します。
- **イベントで監視**。定期ポーリング、ログの走査、監視状態の定期保存は行いません。
- **設定は3項目**。Discord Webhook URL、送信元ラベル、自動起動を設定します。
- **ネイティブ実行**。Python・Qt・WebViewの同梱や、起動時の自己展開はありません。

## ダウンロード

[GitHub Releases](https://github.com/AkaakuHub/codex-goal-monitor/releases/latest)の**Assets**から、お使いのOS用のファイルを取得します。`v`から始まるバージョンタグを付けると、GitHub Actionsで5環境の検証とビルドを行い、すべて成功した場合にReleaseへ公開します。タグとアプリのバージョンが異なる場合は公開しません。開発中のビルドは[GitHub ActionsのBuild](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml)の**Artifacts**から取得できます。Artifactsの保持期間は14日です。

| OS | Releaseのファイル | 動作 |
| --- | --- | --- |
| Windows x64 | `codex-goal-monitor-windows-x64-setup.exe` | タスクトレイに常駐します |
| macOS Apple Silicon | `codex-goal-monitor-macos-arm64.pkg` | メニューバーに常駐します |
| macOS Intel | `codex-goal-monitor-macos-x64.pkg` | メニューバーに常駐します |
| Linux x64 | `codex-goal-monitor-linux-x64.tar.gz` | GUIなしで常駐します |
| Linux ARM64 | `codex-goal-monitor-linux-arm64.tar.gz` | GUIなしで常駐します |

WindowsはセットアップEXEを開きます。管理者権限は不要で、現在のユーザーの`%LOCALAPPDATA%\Programs\Codex Goal Monitor`にインストールし、スタートメニューへ登録します。削除するときはWindowsの「インストールされているアプリ」からアンインストールします。自動起動の登録も削除し、設定ファイルは保持します。

macOSはPKGを開き、インストーラーの案内に従います。管理者権限は不要で、現在のユーザーの`~/Applications/Codex Goal Monitor.app`にインストールします。削除するときはアプリ内で自動起動を解除して終了し、この`.app`をゴミ箱へ移動してください。

更新するときはアプリを終了してから新しいインストーラーを実行します。WindowsのセットアップEXEはコード署名を付けていません。macOSのアプリはアドホック署名のみで、PKGの署名とAppleの公証は行っていません。OSによって初回実行が制限される場合があります。

Linuxは`.tar.gz`を解凍して使用します。ActionsのArtifactsから取得した場合は、外側のZIPを解凍するとインストーラーまたは`.tar.gz`が入っています。

## はじめに

必要なものは、**Codex CLIのローカル共有app-server**と**Discord Webhook URL**です。Codex CLI 0.163.0で動作を検証しています。

1. Codexを通常どおり`codex`で起動します。
2. Windows・macOSではアプリを起動し、トレイの「設定ファイルを開く」からJSONの`webhook_url`と`sender_label`を編集して保存します。初回起動時に設定ファイルを作成します。入力ダイアログや設定画面はありません。
3. トレイの「設定を再読み込み」を選ぶと監視を開始します。自動起動する場合は「ログイン時に自動起動」にチェックを入れます。「終了」でアプリを終了します。

`--no-daemon`や独自の`--remote`接続は監視対象外です。WSLではLinux版を使ってください。カスタムの`CODEX_HOME`を使う場合は、Codexと監視アプリで同じ絶対パスを指定します。

### Linux・headless環境

次のJSONを`settings.json`として保存し、Webhook URLを実際の値に置き換えます。

```json
{
  "webhook_url": "https://discord.com/api/webhooks/123456789/WEBHOOK_TOKEN",
  "sender_label": "開発サーバー",
  "autostart": false
}
```

```sh
chmod 600 settings.json
./codex-goal-monitor --headless --config ./settings.json
```

Windows・macOSも`--headless`またはSSH接続時はGUIなしで動作します。

## 設定

| 項目 | 内容 |
| --- | --- |
| `webhook_url` | Discordの通知先です。設定ファイルへURLを記入します。未入力の場合は監視を開始しません |
| `sender_label` | 通知の送信者名と本文に表示する、1〜80文字のラベルです |
| `autostart` | 自動起動の設定です。既定値は`false`です。トレイまたは下記のコマンドから変更します |

設定はJSONで保存します。Webhook URLは平文で、アプリから保存するUnixファイルの権限は`600`です。

| OS | 既定の保存先 |
| --- | --- |
| Windows | `%APPDATA%\codex-goal-monitor\settings.json` |
| macOS | `~/Library/Application Support/codex-goal-monitor/settings.json` |
| Linux | `~/.config/codex-goal-monitor/settings.json`。`XDG_CONFIG_HOME`設定時はその配下です |

`--config`で保存先を指定できます。ファイルを編集したらトレイの「設定を再読み込み」を選びます。設定が不正な場合は監視を停止し、トレイメニューにエラーを表示します。headless環境では編集後に再起動してください。同じ設定での多重起動は防止します。

### 自動起動

インストール後、または実行ファイルの配置場所を決めてから登録してください。Webhook URLが未入力でも登録できます。

Windows・Linuxとも、現在のユーザーのスコープで登録・実行します。Windowsはインストール・実行ともに管理者権限が不要です。Linuxはsystemdのユーザーマネージャーが動いているログインセッションで、sudoを使わずに登録・開始できます。

```sh
./codex-goal-monitor --config ./settings.json --headless --autostart on
./codex-goal-monitor --config ./settings.json --autostart status
./codex-goal-monitor --config ./settings.json --autostart off
```

`on`・`off`は設定とOSへの登録を変更して終了します。現在の監視は起動・停止しません。JSONの値だけを書き換えてもOSの登録は変更されません。`--headless`で登録すると、次回もGUIなしで起動します。GUIで使うWindows・macOSではトレイから設定してください。

| OS | 登録先・使用ライブラリ |
| --- | --- |
| Windows | 現在のユーザーのRunレジストリに、`windows-registry`で登録します |
| macOS | ユーザーのLaunchAgentを、`plist`で作成します |
| Linux | systemdのユーザーサービスとして登録します |

Windows・macOSでは次回ログイン時に起動します。Linuxでは登録後、`systemctl --user start codex-goal-monitor.service`で開始できます。ログイン前の起動やログアウト後の継続には、OS側でユーザーのlingerを有効にする必要があります。OS側の起動制限・承認も適用されます。

ファイルの移動・削除前には自動起動を解除してください。Linux・macOSは登録時の`CODEX_HOME`を保存します。Windowsでカスタムの値を使う場合は、ユーザー環境変数として設定してください。

## 復旧と通知

- Goalがないスレッドも監視し、直近30分以内のCapacityエラー・HTTP429・ストリーム切断から再開します。接続時とスレッドの停止時に確認し、同じ失敗に対して重複操作しません。
- Goalなしの場合は、再開直前に最新ターンが同じ失敗のままであることを確認し、`continue`を送ります。復旧後も失敗する状態が5回続くと停止します。
- 同じGoalが`blocked`で、直近の失敗がCapacityエラー・HTTP429・ストリーム切断の場合だけ再開します。再開直前にも状態を確認します。
- 再試行の待機時間は30・60・120・300・600秒です。トークンを消費する復旧失敗が5回続くと停止します。消費のないCapacityエラーは回数だけで停止しません。
- 手動停止、Goal完了、利用上限、予算上限では再開しません。
- Goal完了、利用上限、復旧の待機・再開・結果をDiscordへ通知します。メンションは無効で、送信は最大5回試みます。

復旧状態・通知履歴はメモリ内に保持し、アプリの再起動でリセットします。切断後の再接続はソケットの変更通知で行い、定期的には確認しません。復旧待機・結果確認・通信期限・通知再送にはタイマーを使います。

## アイコンとバージョン

専用アイコンの元データは[SVG](assets/icons/app.svg)です。Windowsの実行ファイル・セットアップEXE、macOSのアプリ、トレイに使用します。macOSのメニューバーではOSが外観に合わせて色を調整します。Linuxにはトレイアイコンがありません。アイコンの再生成にはImageMagickと`python assets/icons/generate.py`を使用します。

アプリのバージョンはCargoの定義から埋め込み、トレイの先頭と`--version`で表示します。macOSのアプリ情報と実行ファイルのバージョンの一致もCIで確認します。

## ビルド・検証

Rust 1.90以上を使用します。

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
```

GitHub Actionsでは5環境でテスト・リリースビルド・バージョン確認・自動起動の登録と解除・配布ファイルの生成を行います。タグのpush・PR・手動実行で起動し、mainへのpushでは起動しません。[v0.2.4の検証実行](https://github.com/AkaakuHub/codex-goal-monitor/actions/runs/40813995411)は全環境で成功しています。

[インストーラーの検証記録](reports/installer-validation.json)には、Windowsの非管理者権限でのインストール・更新・アンインストールと、macOSのApple Silicon・Intelでのユーザー専用PKGのインストール・起動を確認した結果を保存しています。

[v0.2.4のRelease](https://github.com/AkaakuHub/codex-goal-monitor/releases/tag/v0.2.4)には、タグ付きビルドで生成したWindowsのセットアップEXE、macOSのPKG2種類、Linuxのアーカイブ2種類を公開しています。[トレイの検証記録](reports/tray-validation.json)には、入力ダイアログを廃止した後の初回起動と設定未入力時の自動起動、SVGアイコンの組み込みを確認した結果を保存しています。

[ユーザースコープの検証記録](reports/user-scope-validation.json)には、ReleaseのWindows版を非管理者権限で起動し、実際のCodexへの接続・多重起動の拒否・自動起動の登録と解除を確認した結果を保存しています。Linuxのx64・ARM64では、CIでユーザーサービスを起動・停止し、プロセスが現在のユーザーの所有であることを確認しています。

[検証記録](reports/native-validation.json)にはLinux ARM64での測定とCIの実行先を保存しています。v0.2.1の実行ファイルは約1.9MB、待機時メモリは約3.3MiBです。5秒間の計測ではCPU時間の増分は0.00秒、ディスク読み書きは0バイトでした。

通常ターミナルとtmuxでの復旧は実際のCodex CLIで検証済みです。Windows・macOSのトレイ操作、再ログイン後の自動起動、実際のDiscordへの通知到着は未検証です。
