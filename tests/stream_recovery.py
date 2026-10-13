import argparse
import json
import os
import shlex
import sqlite3
import subprocess
import time
from pathlib import Path

from local_provider import Provider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--capacity-retries', type=int, default=0)
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = Path(__file__).resolve().parents[1]
    home = root / 'home'
    home.mkdir(exist_ok=True)
    provider = Provider()
    socket = root / 'tmux.sock'
    (home / 'config.toml').write_text(f'''model = "gpt-6.1-sol"
model_provider = "local_test"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[features]
goals = true
responses_websockets_v2 = false
[tui]
terminal_title = ["session-id"]
[model_providers.local_test]
name = "Local test"
base_url = "{provider.url}/v1"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
requires_openai_auth = false
[projects.{json.dumps(str(root))}]
trust_level = "trusted"
''')
    values = {'runtime': str(root / 'runtime'), 'state': str(root / 'state'), 'helper': str(Path.home() / '.local/lib/codex-goal-monitor/events'), 'socket_directories': [], 'sockets': [str(socket)], 'codex_homes': [str(home)], 'retry_delays': [0.5] if args.capacity_retries else [2, 3, 4]}
    config = root / 'monitor.toml'
    config.write_text('\n'.join(f'{k} = {json.dumps(v)}' for k, v in values.items()))
    config.chmod(0o600)
    results: list[str] = []

    def tmux(*args: str) -> str:
        return subprocess.check_output(['tmux', '-S', str(socket), *args], stderr=subprocess.DEVNULL).decode().strip()

    def wait(label: str, condition, timeout: float = 45):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if condition():
                    results.append(label)
                    print('PASS', label, flush=True)
                    return
            except (OSError, sqlite3.Error, ValueError):
                pass
            time.sleep(0.15)
        raise AssertionError(label)

    log = (root / 'monitor.log').open('w')
    monitor = subprocess.Popen(['/usr/bin/python3', '-m', 'monitor.service', '--config', str(config)], cwd=project, env=dict(os.environ, DISCORD_WEBHOOK_URL=provider.url + '/webhook'), stdout=log, stderr=log)
    try:
        pane = tmux('new-session', '-d', '-s', 'stream-test', '-x', '160', '-y', '45', '-P', '-F', '#{pane_id}')
        launch = f'env -u CODEX_THREAD_ID CODEX_HOME={shlex.quote(str(home))} codex --no-daemon --no-alt-screen -C {shlex.quote(str(root))} "Local test only."'
        tmux('send-keys', '-t', pane, '-l', launch)
        tmux('send-keys', '-t', pane, 'Enter')
        wait('隔離した実Codexを検出', lambda: len(json.loads((root / 'state/status.json').read_text())) == 1)
        wait('初回Capacityターン終了', lambda: 'Selected model is at capacity' in tmux('capture-pane', '-p', '-t', pane))
        tmux('send-keys', '-t', pane, '-l', '/goal Complete the local test.')
        time.sleep(0.3)
        tmux('send-keys', '-t', pane, 'Enter')
        wait('GoalのCapacityエラーを通知', lambda: any('Codex Capacity Error' in text for text in provider.webhooks))
        if args.capacity_retries:
            wait('Capacityが5回を超えても自動再開を継続', lambda: sum('Codex Capacity Error' in text for text in provider.webhooks) >= args.capacity_retries, 90)
            recovery = next(iter(json.loads((root / 'state/recovery.json').read_text()).values()))
            if recovery['halted'] or recovery['resumes'] < 5:
                raise AssertionError('5回上限が残っている')
            provider.mode = 'success'
            wait('連続Capacityの解消後に実ターンが正常終了', lambda: any('Codex Goal Resumed\n' in text for text in provider.webhooks))
        else:
            provider.mode = 'stream'
            wait('再開開始を成功とは分けて通知', lambda: any('Codex Goal Resume Started' in text for text in provider.webhooks))
            wait('再開後の実ストリーム切断を失敗として通知', lambda: any('Codex Stream Error' in text for text in provider.webhooks))
            if any('Codex Goal Resumed\n' in text for text in provider.webhooks):
                raise AssertionError('通信エラーを復旧成功として通知した')
            results.append('失敗ターンに成功通知を出さない')
            provider.mode = 'success'
            wait('通信エラー後もblockedのGoalを再試行し正常終了を確認', lambda: any('Codex Goal Resumed\n' in text for text in provider.webhooks))
        (root / 'results.json').write_text(json.dumps({'passed': results, 'notifications': provider.webhooks}, ensure_ascii=False, indent=2))
    finally:
        monitor.terminate()
        monitor.wait(timeout=10)
        subprocess.run(['tmux', '-S', str(socket), 'kill-server'], stderr=subprocess.DEVNULL, check=False)
        provider.shutdown()
        log.close()


if __name__ == '__main__':
    main()
