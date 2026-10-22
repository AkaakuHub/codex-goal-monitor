# Codex Goal Monitor

CodexのGoalを監視し、Capacityエラー・ストリーム切断から復旧してDiscordへ通知します。Windowsネイティブ、macOS、Linuxに対応するRust製の常駐アプリです。

## 動作

- Windowsではタスクトレイ、macOSではメニューバーにアイコンを表示します。
- Linux版はheadless専用で、GUI関連のコードを含みません。
- Windows・macOSでも`--headless`またはSSH接続ではGUIを初期化しません。
- tmux内と通常のターミナルで動くCodexを、同じ接続で監視します。

監視側はCodexのイベントを待ちます。プロセスやディスクの定期スキャン、セッションログの走査、監視状態の定期保存は行いません。復旧判定時だけ直近2ターンの情報をAPIから取得します。タイマーはエラー後の待機と処理期限に使用します。

Python、Qt、WebViewは同梱しません。起動時の自己展開も行いません。設定画面を開いたときだけOSの入力ダイアログを使用します。

## 必要なもの

- Codex CLI 0.163.0以上と、標準起動で使用するローカル共有app-server
- Discord Webhook URL

Codexは通常どおり`codex`で起動します。共有サーバーを無効化する`--no-daemon`と、別の接続先を指定する`--remote`は監視対象外です。監視アプリからスレッドを読み込んだり、Codexの起動設定を変更したりすることはありません。[Codexの接続仕様](https://learn.chatgpt.com/docs/app-server)を使用しています。

カスタムのCodexホームを使用する場合は、Codexと監視アプリに同じ`CODEX_HOME`の絶対パスを設定してください。WSL内のCodexにはLinux版を使用します。

## 配布ファイルと起動

[動作確認済みのビルド](https://github.com/AkaakuHub/codex-goal-monitor/actions/runs/39759982937)のArtifactsからダウンロードできます。Windows版は[codex-goal-monitor-windows-x64](https://github.com/AkaakuHub/codex-goal-monitor/actions/runs/39759982937/artifacts/12418061290)を選び、ダウンロードしたZIPと、その中のZIPを解凍してください。Artifactsの保持期間は14日です。

GitHub Actionsの`Build`では次のファイルを生成します。

| 対象 | 内容 |
| --- | --- |
| Windows x64 | `.exe`を含むZIP |
| macOS Apple Silicon・Intel | メニューバー用の`.app`を含むZIP |
| Linux x64・ARM64 | 実行ファイルを含む`.tar.gz` |

解凍後、Windowsでは`.exe`、macOSでは`.app`を起動します。Linuxでは`./codex-goal-monitor`を実行します。macOSのビルドはアドホック署名を付けますが、Appleの公証は行いません。

トレイの「設定…」からWebhook URLと送信元ラベルを保存します。Webhook URLは入力時に隠し、空欄で確定した場合は現在の値を保持します。ラベルはDiscordの送信者名と通知本文に使用します。

## headless環境の設定

設定JSONを作成します。URLは実際のWebhook URLに置き換えてください。

```json
{
  "webhook_url": "https://discord.com/api/webhooks/123456789/WEBHOOK_TOKEN",
  "sender_label": "開発サーバー"
}
```

既定の保存先はLinuxの`~/.config/codex-goal-monitor/settings.json`（`XDG_CONFIG_HOME`設定時はその配下）、macOSの`~/Library/Application Support/codex-goal-monitor/settings.json`、Windowsの`%APPDATA%\codex-goal-monitor\settings.json`です。Webhookは設定ファイルに保存します。アプリから保存したファイルのUnix権限は600です。

```sh
chmod 600 /設定ファイルの絶対パス/settings.json
./codex-goal-monitor --headless --config /設定ファイルの絶対パス/settings.json
```

設定変更はトレイで保存すると反映されます。headless環境でファイルを編集した場合は、監視アプリを再起動してください。同じ設定を使うアプリの多重起動は防止します。

## Linuxのユーザーサービス

実行ファイルを`~/.local/opt/codex-goal-monitor/codex-goal-monitor`へ配置し、[サービス定義](deploy/codex-goal-monitor.service)を`~/.config/systemd/user/`へコピーします。

```sh
systemctl --user daemon-reload
systemctl --user enable --now codex-goal-monitor.service
journalctl --user -u codex-goal-monitor.service -f
```

サービスはheadlessで起動します。トレイ版と同時に起動しないでください。カスタムの`CODEX_HOME`を使用する場合は、サービスにも環境変数を設定します。

## 自動復旧の条件

同じGoalの直近のターンがCapacityエラー・HTTP 429・ストリーム切断で失敗し、Goalが`blocked`の場合だけ再開を予約します。再開直前にも、スレッドが読み込み済みで処理中ではないことと、同じGoalが`blocked`であることをAPIから確認します。端末へのキー送信は行いません。

- 待機時間は30・60・120・300・600秒です。再開後のターンが正常終了すると連続回数をリセットします。
- トークン消費のないCapacityエラーは回数だけを理由に停止しません。トークンを消費する復旧失敗が5回続いた場合は停止して通知します。
- 手動停止、完了、利用上限、予算上限では再開しません。Goal完了と利用上限をDiscordへ通知します。
- 再開要求の結果が不明な場合は追加操作を停止します。Discord通知は最大5回再送し、HTTP 429では指定された待機時間を使用します。

復旧状態と通知履歴はメモリ内に保持します。監視アプリの再起動でリセットされます。切断後はソケットの作成・変更イベント、または設定の再保存で再接続します。定期的な再接続は行いません。

## 開発

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
```

出力先は`target/release/codex-goal-monitor`です。Windowsでは拡張子が`.exe`になります。GitHub Actionsでは各OSでテストとネイティブビルドを実行します。

## 検証結果

[検証結果](reports/native-validation.json)にLinux ARM64での測定を保存しています。実行ファイルは約1.8MBです。接続後の5秒間の待機測定ではRSSが約3.2MiB、CPU時間の増分は0.00秒、ディスク読み書きの増分は0バイトでした。子プロセスはありません。

Codex CLI 0.163.0を使い、通常のターミナルとtmuxの両方でCapacityエラーからの再開と、その後のターンの正常終了を確認しました。通知の送信元ラベルとHTTP429の再送はローカルHTTPサーバーで検証しています。実際のDiscordへの送信と、Windows・macOSのトレイ操作は未検証です。GitHub Actionsでは5種類すべてでClippy、テスト、リリースビルド、実行ファイルの起動確認、配布ファイルの生成に成功しました。Windowsの起動確認は`--version`、Linux・macOSは`--help`で行っています。

このLinux ARM64環境では旧Python版を停止し、Rust版をユーザーサービスとして起動しました。既存のWebhook設定を引き継ぎ、実際のCodexへの接続と監視開始を確認済みです。自動起動が有効で、ログアウト後も動作する設定です。
