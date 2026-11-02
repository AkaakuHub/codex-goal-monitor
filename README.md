# Codex Goal Monitor

[![Build](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml/badge.svg)](https://github.com/AkaakuHub/codex-goal-monitor/actions/workflows/build.yml)

Codex CLIのCapacityエラー・HTTP429・通信切断を検知し、作業を自動再開する常駐アプリです。通常のターミナルとtmuxに対応し、Goalがないスレッドも監視します。Discordへの通知は任意です。

## インストール

[GitHub Releases](https://github.com/AkaakuHub/codex-goal-monitor/releases/latest)から、お使いの環境に合うファイルを取得してください。

| OS | ファイル |
| --- | --- |
| Windows x64 | `codex-goal-monitor-windows-x64-setup.exe` |
| macOS Apple Silicon | `codex-goal-monitor-macos-arm64.pkg` |
| macOS Intel | `codex-goal-monitor-macos-x64.pkg` |
| Linux x64 | `codex-goal-monitor-linux-x64.tar.gz` |
| Linux ARM64 | `codex-goal-monitor-linux-arm64.tar.gz` |

Windows・macOSはインストーラーを実行します。管理者権限は不要です。Linuxはアーカイブを解凍します。

## 使い方

1. Codex CLIを`codex`で起動します。
2. Codex Goal Monitorを起動すると、監視が始まります。

Windowsではタスクトレイ、macOSではメニューバーに常駐します。Linuxではターミナルから起動します。

```sh
./codex-goal-monitor
```

Codex CLIのローカル共有app-serverに接続します。`--no-daemon`や独自の`--remote`接続は監視対象外です。WSLではLinux版を使用してください。`CODEX_HOME`を変更している場合は、Codex CLIと本アプリに同じ絶対パスを指定します。

## 設定

初回起動時に`settings.json`を作成します。初期設定のまま監視と自動復旧を利用できます。

```json
{
  "webhook_url": "",
  "sender_label": "Codex",
  "autostart": false
}
```

| 項目 | 内容 |
| --- | --- |
| `webhook_url` | Discordへ通知する場合に入力します。空欄の場合は送信しません |
| `sender_label` | Discord通知に表示する送信元名です。通知を利用する場合は1〜80文字で指定します |
| `autostart` | 自動起動の設定です。トレイメニューまたはコマンドで変更します |

| OS | 設定ファイルの保存先 |
| --- | --- |
| Windows | `%APPDATA%\codex-goal-monitor\settings.json` |
| macOS | `~/Library/Application Support/codex-goal-monitor/settings.json` |
| Linux | `~/.config/codex-goal-monitor/settings.json`。`XDG_CONFIG_HOME`設定時はその配下です |

Windows・macOSではトレイの「設定ファイルを開く」から編集し、「設定を再読み込み」で反映します。Linuxや`--headless`での実行時は、編集後にアプリを再起動してください。Webhook URLは平文で保存します。

別の設定ファイルを使う場合は`--config`を指定します。Windows・macOSでも`--headless`を指定するとトレイを表示せずに動作します。

```sh
./codex-goal-monitor --headless --config ./settings.json
```

## 自動起動

Windows・macOSでは、トレイの「ログイン時に自動起動」で切り替えます。コマンドでも登録・確認・解除できます。

```sh
./codex-goal-monitor --headless --autostart on
./codex-goal-monitor --autostart status
./codex-goal-monitor --autostart off
```

各コマンドは設定を変更・確認して終了します。JSONの`autostart`だけを編集してもOSへの登録は変更されません。Linuxではsystemdのユーザーサービスとして登録し、次のコマンドで開始します。

```sh
systemctl --user start codex-goal-monitor.service
```

実行ファイルを移動・削除する前に、自動起動を解除してください。

## 自動復旧と通知

- Capacityエラー・HTTP429・通信切断から再開します。Goalがない場合は直近30分以内の失敗を対象に、`continue`を送信します。
- Goalがある場合は、同じGoalが`blocked`で、直近の失敗が対象のエラーであることを確認して再開します。
- 再試行は30・60・120・300・600秒待機します。トークンを消費する復旧失敗が5回続くと停止します。消費のないCapacityエラーは回数だけでは停止しません。
- 手動停止・Goal完了・利用上限・予算上限では再開しません。
- Webhook URLを設定している場合、Goal完了・利用上限・復旧の待機や結果をDiscordへ通知します。

復旧状態と通知履歴はアプリの終了時にリセットします。

## ビルド

Rust 1.90以上を使用します。

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
```
