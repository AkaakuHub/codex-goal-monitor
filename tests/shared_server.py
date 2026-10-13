import argparse
import json
import os
import shlex
import socket
import sqlite3
import subprocess
import time
from pathlib import Path

from local_provider import Provider

parser = argparse.ArgumentParser()
parser.add_argument('--directory', type=Path, required=True)
args = parser.parse_args()
root = args.directory.resolve()
root.mkdir(parents=True, exist_ok=True)
root.chmod(0o700)
project = Path(__file__).resolve().parents[1]
provider = Provider()
home = root / 'home'
home.mkdir(exist_ok=True)
(home / 'config.toml').write_text(f'''model = "gpt-6.1-sol"
model_provider = "local_test"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[features]
goals = true
responses_websockets_v2 = false
[tui]
terminal_title = ["model"]
status_line = ["model"]
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
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    app_port = listener.getsockname()[1]
app_uri = f'ws://127.0.0.1:{app_port}'
tmux_socket = root / 'tmux.sock'
app_log = (root / 'app.log').open('w')
env = dict(os.environ, CODEX_HOME=str(home))
app = subprocess.Popen(['codex', 'app-server', '--listen', app_uri], env=env, stdout=app_log, stderr=app_log)
configuration = root / 'monitor.toml'
configuration.write_text('\n'.join(f'{key} = {json.dumps(value)}' for key, value in {
    'runtime': str(root / 'runtime'), 'state': str(root / 'state'), 'helper': str(Path.home() / '.local/lib/codex-goal-monitor/events'), 'socket_directories': [], 'sockets': [str(tmux_socket)], 'codex_homes': [str(home)], 'retry_delays': [2, 3, 4],
}.items()))
configuration.chmod(0o600)
monitor_env = dict(os.environ, DISCORD_WEBHOOK_URL=provider.url + '/webhook')
log = (root / 'monitor.log').open('w')
monitor = subprocess.Popen(['python3', '-m', 'monitor.service', '--config', str(configuration)], cwd=project, env=monitor_env, stdout=log, stderr=log)
results: list[str] = []


def wait(description: str, condition, timeout: float = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = condition()
            if result:
                print('PASS', description, flush=True)
                results.append(description)
                return result
        except (FileNotFoundError, sqlite3.Error, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(0.15)
    raise AssertionError(description)


def tmux(*arguments: str) -> str:
    return subprocess.check_output(['tmux', '-S', str(tmux_socket), *arguments], stderr=subprocess.DEVNULL).decode().strip()


def goal_status() -> str:
    with sqlite3.connect(home / 'goals_1.sqlite') as db:
        row = db.execute('SELECT status FROM thread_goals').fetchone()
        return row[0] if row else ''


def app_ready() -> bool:
    try:
        with socket.create_connection(('127.0.0.1', app_port), timeout=0.2):
            return True
    except OSError:
        return False


try:
    wait('独立した共有app-server起動', app_ready)
    pane = tmux('new-session', '-d', '-s', 'shared-server-test', '-x', '120', '-y', '35', '-P', '-F', '#{pane_id}')
    launch = f'env -u CODEX_THREAD_ID CODEX_HOME={shlex.quote(str(home))} codex --no-alt-screen --remote {app_uri} -C {shlex.quote(str(root))} "Local shared-server discovery test."'
    tmux('send-keys', '-t', pane, '-l', launch)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('共有app-serverのTUI起動', lambda: 'Selected model is at capacity.' in tmux('capture-pane', '-p', '-t', pane))
    wait('タイトルにもFDにもIDのないCLIを発見', lambda: len(json.loads((root / 'state/status.json').read_text())) == 1)
    if json.loads((root / 'state/status.json').read_text())[0]['thread_id'] is not None:
        raise AssertionError('復旧前はIDが未確定')
    tmux('send-keys', '-t', pane, '-l', '/goal Perform the shared-server recovery integration test.')
    time.sleep(0.25)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('共有app-serverのGoalがblocked', lambda: goal_status() == 'blocked')
    provider.mode = 'success'
    wait('/statusから実際のThreadを確定', lambda: json.loads((root / 'state/status.json').read_text())[0]['thread_id'])
    wait('再開直前にもThreadを確認しactiveへ復旧', lambda: goal_status() == 'active' and any('Codex Goal Resumed' in text for text in provider.webhooks))
    tmux('send-keys', '-t', pane, '-l', '/goal pause')
    time.sleep(0.25)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('検証後にpause', lambda: goal_status() == 'paused')
    monitor.terminate()
    monitor.wait(timeout=10)
    tmux('kill-session', '-t', 'shared-server-test')
    pane = tmux('new-session', '-d', '-s', 'complete-test', '-x', '120', '-y', '35', '-P', '-F', '#{pane_id}')
    provider.mode = 'success'
    tmux('send-keys', '-t', pane, '-l', launch)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('Capacityなしの完了テスト用CLI起動', lambda: 'Local test completed.' in tmux('capture-pane', '-p', '-t', pane))
    with sqlite3.connect(home / 'state_5.sqlite') as db:
        complete_thread = db.execute('SELECT id FROM threads ORDER BY created_at_ms DESC LIMIT 1').fetchone()[0]
    tmux('send-keys', '-t', pane, '-l', '/goal Perform the isolated completion notification test.')
    time.sleep(0.25)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('完了テストのGoal作成', lambda: 'Pursuing goal' in tmux('capture-pane', '-p', '-t', pane))
    subprocess.run(['node', str(project / 'tests/complete_goal.mjs'), app_uri, complete_thread], check=True)
    wait('実TUIのGoal achieved表示', lambda: 'Goal achieved' in tmux('capture-pane', '-p', '-t', pane))
    monitor = subprocess.Popen(['python3', '-m', 'monitor.service', '--config', str(configuration)], cwd=project, env=monitor_env, stdout=log, stderr=log)
    wait('ID未確定のcompleteを読み取り専用で確定して通知', lambda: any('Codex Goal Completed' in text and complete_thread in text for text in provider.webhooks))
    (root / 'results.json').write_text(json.dumps({'passed': results}, ensure_ascii=False, indent=2))
except BaseException:
    (root / 'failure-screen.txt').write_text(tmux('capture-pane', '-p', '-t', pane))
    (root / 'failure-cursor.txt').write_text(tmux('display-message', '-p', '-t', pane, '#{cursor_x}|#{cursor_y}'))
    raise
finally:
    monitor.terminate()
    monitor.wait(timeout=10)
    subprocess.run(['tmux', '-S', str(tmux_socket), 'kill-server'], check=False, stderr=subprocess.DEVNULL)
    app.terminate()
    app.wait(timeout=10)
    provider.shutdown()
    log.close()
    app_log.close()
