# Codex Goal Monitor

同じUnixユーザーのtmuxで動くCodex CLIを自動発見し、Capacityエラーまたはストリーム切断（remote compactの通信エラーを含みます）でblockedになったGoalを`/goal resume`で再開します。復旧状況・使用量制限・Goal完了をDiscordへ通知します。

## 動作環境

- Linux、Python 3.12以上、tmux、Cコンパイラ、Codex CLI
- systemdのユーザーサービス
- Discord Webhook

Codex CLI 0.162.1、tmux 3.4、Python 3.12で検証しています。

## 導入

リポジトリのディレクトリで、次のコマンドをBashから実行します。

```bash
read -r -s -p 'Discord Webhook URL: ' DISCORD_WEBHOOK_URL
export DISCORD_WEBHOOK_URL
python3 deploy/install.py
unset DISCORD_WEBHOOK_URL
systemctl --user daemon-reload
systemctl --user enable --now codex-goal-monitor.service
```

導入時にイベント通知用プログラムをコンパイルし、設定とsystemdユニットを作成します。Codexの`[tui].terminal_title`を`["session-id"]`へ変更し、変更前の設定を保存します。実行中のCodexやtmuxペインは再起動しません。

再導入は`python3 deploy/install.py`を実行します。その後、`systemctl --user daemon-reload`を実行してサービスを再起動します。

## 操作

```sh
systemctl --user start codex-goal-monitor.service
systemctl --user stop codex-goal-monitor.service
systemctl --user restart codex-goal-monitor.service
systemctl --user status codex-goal-monitor.service
journalctl --user -u codex-goal-monitor.service -f
cat ~/.local/state/codex-goal-monitor/status.json
```

SSH切断後も稼働させる場合は、`loginctl show-user "$USER" -p Linger`でユーザーサービスの設定を確認してください。実際のSSH切断は未検証です。

## 設定と保存先

| 用途 | パス |
| --- | --- |
| 設定 | `~/.config/codex-goal-monitor/config.toml` |
| Webhook | `~/.config/codex-goal-monitor/monitor.env` |
| systemdユニット | `~/.config/systemd/user/codex-goal-monitor.service` |
| 監視状況 | `~/.local/state/codex-goal-monitor/status.json` |
| 復旧状態 | `~/.local/state/codex-goal-monitor/recovery.json` |
| 導入前のCodex設定 | `~/.config/codex-goal-monitor/codex-config.before-monitor.toml` |

`config.toml`で監視先を指定します。

- `socket_directories`: tmuxソケットの検索先。既定値は`/tmp/tmux-<UID>`です。
- `sockets`: 個別のtmuxソケットの絶対パスです。
- `codex_homes`: Codexホームの初回監視先です。発見したプロセスの`CODEX_HOME`も自動追加します。

Webhookは`monitor.env`の`DISCORD_WEBHOOK_URL`に保存します。形式は[設定例](deploy/monitor.env.example)を参照してください。設定ファイルの権限は600、設定ディレクトリは700です。設定やWebhookの変更後はサービスを再起動します。

## 自動復旧の条件

Capacityエラーと同じGoalであること、SQLiteの`blocked`、TUIの`Goal stalled (/goal resume)`、空の入力欄、PID・TTY・threadの一致を確認して再開します。状態を確認できない場合や入力できない場合は、自動入力を行いません。

| Goalの状態 | 処理 |
| --- | --- |
| `blocked` | Capacityエラーとの関連を確認して再開します。 |
| `usage_limited` | 通知します。 |
| `complete` | 完了を通知します。 |
| `active`、`paused`、`budget_limited` | 再開しません。 |

- 再試行の待機時間は30・60・120・300・600秒で、成功すると連続回数をリセットします。Capacityエラーだけを理由に回数上限で停止しません。新しいツール実行結果がないままトークンを消費する失敗が5回続く場合は停止して通知します。ツール出力のハッシュを照合し、同じ出力の繰り返しを新しい結果として扱いません。
- Goalがactiveへ変化した時点では開始通知を送り、再開後の最初のターンが正常終了してから成功を通知します。通信エラーや実行エラーで終了した場合は失敗を通知します。activeのままのGoalへ再開コマンドは送信しません。
- 45秒以内にGoalの`active`を確認できない場合は、自動入力を停止して通知します。
- thread IDを取得できない既存CLIでは、復旧や通知に必要な場合に`/status`でIDを確認します。再開直前にも同じthreadであることを確認します。
- 既存のtmuxフックと`pipe-pane`を保持し、tmuxサーバーの再起動後は再接続します。
- 画面・プロンプト・ソースコードはログやDiscordへ保存しません。通知には接続先・ペイン・thread ID・Goal状態を含めます。

## テスト

```sh
python3 -m unittest discover -s tests -v
python3 tests/integration.py --directory <テスト用ディレクトリの絶対パス>
python3 tests/stream_recovery.py --directory <テスト用ディレクトリの絶対パス>
python3 tests/shared_server.py --directory <テスト用ディレクトリの絶対パス>
```

統合テストは別のtmuxソケット・Codexホーム・ローカルの疑似APIで実際のCodex CLIを起動します。共有app-serverの完了状態の注入にはNode.jsのWebSocketを使用します。テスト用ディレクトリは利用後に削除してください。

検証結果は[reports/validation.json](reports/validation.json)に保存しています。
