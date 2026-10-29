# Codex Goal Monitor

[![Build](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml/badge.svg)](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml)

CodexのGoalを監視し、Capacityエラーや通信切断から自動復旧してDiscordへ通知する、Rust製の常駐アプリです。

- **Windows・macOS・Linuxに対応**。通常のターミナルとtmuxの両方を監視します。
- **イベントで監視**。定期ポーリング、ログの走査、監視状態の定期保存は行いません。
- **設定は3項目**。Discord Webhook URL、送信元ラベル、自動起動を設定します。
- **ネイティブ実行**。Python・Qt・WebViewの同梱や、起動時の自己展開はありません。

## ダウンロード

[GitHub Releases](https://github.com/AkaakuHub/codex-goal-monitor/releases/latest)の**Assets**から、お使いのOS用のファイルを取得します。`v`から始まるバージョンタグを付けると、GitHub Actionsで5環境の検証とビルドを行い、すべて成功した場合にReleaseへ公開します。タグとアプリのバージョンが異なる場合は公開しません。開発中のビルドは[GitHub ActionsのBuild](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml)の**Artifacts**から取得できます。Artifactsの保持期間は14日です。

| OS | Artifact | 動作 |
| --- | --- | --- |
| Windows x64 | `codex-goal-monitor-windows-x64` | タスクトレイに常駐します |
| macOS Apple Silicon | `codex-goal-monitor-macos-arm64` | メニューバーに常駐します |
| macOS Intel | `codex-goal-monitor-macos-x64` | メニューバーに常駐します |
| Linux x64 | `codex-goal-monitor-linux-x64` | GUIなしで常駐します |
| Linux ARM64 | `codex-goal-monitor-linux-arm64` | GUIなしで常駐します |

ReleaseのZIPまたは`.tar.gz`を解凍してください。Artifactsから取得した場合は、外側のZIPも解凍してください。Windowsでは`.exe`、macOSでは`.app`、Linuxでは実行ファイルを使用します。macOSの`.app`はApplicationsフォルダへ移動してください。アドホック署名を付けていますが、Appleの公証は行っていません。

## はじめに

必要なものは、**Codex CLIのローカル共有app-server**と**Discord Webhook URL**です。Codex CLI 0.163.0で動作を検証しています。

1. Codexを通常どおり`codex`で起動します。
2. Windows・macOSではアプリを起動し、Webhook URLと送信元ラベルを入力します。
3. 自動起動する場合は、トレイの「ログイン時に自動起動」にチェックを入れます。

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
| `webhook_url` | Discordの通知先です。設定画面では入力を隠し、空欄で確定すると現在の値を保持します |
| `sender_label` | 通知の送信者名と本文に表示する、1〜80文字のラベルです |
| `autostart` | 自動起動の設定です。既定値は`false`です。トレイまたは下記のコマンドから変更します |

設定はJSONで保存します。Webhook URLは平文で、アプリから保存するUnixファイルの権限は`600`です。

| OS | 既定の保存先 |
| --- | --- |
| Windows | `%APPDATA%\codex-goal-monitor\settings.json` |
| macOS | `~/Library/Application Support/codex-goal-monitor/settings.json` |
| Linux | `~/.config/codex-goal-monitor/settings.json`。`XDG_CONFIG_HOME`設定時はその配下です |

`--config`で保存先を指定できます。トレイからの変更は保存時に反映されます。headless環境でファイルを編集した場合は再起動してください。同じ設定での多重起動は防止します。

### 自動起動

Webhook設定後、実行ファイルの配置場所を決めてから登録してください。

Windows・Linuxとも、現在のユーザーのスコープで登録・実行します。Windowsは管理者として実行する必要がなく、ユーザーが書き込めるフォルダへ展開して使用できます。Linuxはsystemdのユーザーマネージャーが動いているログインセッションで、sudoを使わずに登録・開始できます。

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

- 同じGoalが`blocked`で、直近の失敗がCapacityエラー・HTTP429・ストリーム切断の場合だけ再開します。再開直前にも状態を確認します。
- 再試行の待機時間は30・60・120・300・600秒です。トークンを消費する復旧失敗が5回続くと停止します。消費のないCapacityエラーは回数だけで停止しません。
- 手動停止、Goal完了、利用上限、予算上限では再開しません。
- Goal完了、利用上限、復旧の待機・再開・結果をDiscordへ通知します。メンションは無効で、送信は最大5回試みます。

復旧状態・通知履歴はメモリ内に保持し、アプリの再起動でリセットします。切断後の再接続はソケットの変更通知で行い、定期的には確認しません。復旧待機・結果確認・通信期限・通知再送にはタイマーを使います。

## アイコンとバージョン

トレイには`tray-icon`の`NativeIcon::Info`を指定しています。WindowsはOS標準の`SIID_INFO`、macOSは`NSImageNameInfo`を表示します。独自の画像は作成しておらず、`.exe`・`.app`用の専用アイコンも未設定です。Linuxにはトレイアイコンがありません。

アプリのバージョンはCargoの定義から埋め込み、トレイの先頭と`--version`で表示します。macOSのアプリ情報と実行ファイルのバージョンの一致もCIで確認します。

## ビルド・検証

Rust 1.90以上を使用します。

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
```

GitHub Actionsでは5環境でテスト・リリースビルド・バージョン確認・自動起動の登録と解除・配布ファイルの生成を行います。[v0.2.1の検証実行](https://github.com/AkaakuHub/codex-goal-monitor/actions/runs/39770474884)は全環境で成功しています。

[検証記録](reports/native-validation.json)にはLinux ARM64での測定とCIの実行先を保存しています。v0.2.1の実行ファイルは約1.9MB、待機時メモリは約3.3MiBです。5秒間の計測ではCPU時間の増分は0.00秒、ディスク読み書きは0バイトでした。

通常ターミナルとtmuxでの復旧は実際のCodex CLIで検証済みです。Windows・macOSのトレイ操作、再ログイン後の自動起動、実際のDiscordへの通知到着は未検証です。
