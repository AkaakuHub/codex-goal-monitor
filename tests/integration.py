import argparse
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from local_provider import Provider

parser = argparse.ArgumentParser()
parser.add_argument('--directory', type=Path, required=True)
args = parser.parse_args()
root = args.directory.resolve()
root.mkdir(parents=True, exist_ok=True)
project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
provider = Provider()
socket = root / 'tmux.sock'
runtime = root / 'runtime'
state = root / 'state'
codex_home = root / 'codex-home'
codex_home.mkdir(exist_ok=True)
configuration = f'''model = "gpt-6.1-sol"
model_provider = "local_test"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[features]
goals = true
responses_websockets_v2 = false
[tui]
terminal_title = ["session-id"]
status_line = ["session-id"]
[model_providers.local_test]
name = "Local test"
base_url = "{provider.url}/v1"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
requires_openai_auth = false
[projects.{json.dumps(str(root))}]
trust_level = "trusted"
'''
(codex_home / 'config.toml').write_text(configuration)
monitor_config = root / 'monitor.toml'
monitor_values = {'runtime': str(runtime), 'state': str(state), 'helper': str(Path.home() / '.local/lib/codex-goal-monitor/events'), 'socket_directories': [], 'sockets': [str(socket)], 'codex_homes': [str(codex_home)], 'retry_delays': [2, 3, 4, 5, 6]}
monitor_config.write_text('\n'.join(f'{key} = {json.dumps(value)}' for key, value in monitor_values.items()))
monitor_config.chmod(0o600)
monitor_env = dict(os.environ, DISCORD_WEBHOOK_URL=provider.url + '/webhook')
log = (root / 'monitor.log').open('w')
monitor = subprocess.Popen(['/usr/bin/python3', '-m', 'monitor.service', '--config', str(monitor_config)], cwd=project, env=monitor_env, stdout=log, stderr=log)
results: list[str] = []


def tmux(*arguments: str) -> str:
    return subprocess.check_output(['tmux', '-S', str(socket), *arguments], stderr=subprocess.DEVNULL).decode().strip()


def wait(description: str, condition, timeout: float = 20):
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


def targets() -> list[dict]:
    return json.loads((state / 'status.json').read_text())


def screen(pane: str) -> str:
    return tmux('capture-pane', '-p', '-t', pane)


def start(pane: str) -> None:
    launch = f'env -u CODEX_THREAD_ID CODEX_HOME={shlex.quote(str(codex_home))} codex --no-daemon --no-alt-screen -C {shlex.quote(str(root))} "Local integration discovery test."'
    tmux('send-keys', '-t', pane, '-l', launch)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('Codex TUI起動 ' + pane, lambda: 'Ask Codex to do anything' in screen(pane) or '›' in screen(pane), 30)


def goal_status(thread: str) -> str:
    with sqlite3.connect(codex_home / 'goals_1.sqlite') as db:
        row = db.execute('SELECT status FROM thread_goals WHERE thread_id=?', (thread,)).fetchone()
        return row[0] if row else ''


try:
    pane = tmux('new-session', '-d', '-s', 'monitor-test', '-x', '160', '-y', '45', '-P', '-F', '#{pane_id}')
    tmux('set-hook', '-g', 'after-split-window[5]', 'set-option -g @test_existing_hook preserved')
    start(pane)
    wait('既存シェル内のCodexを自動発見', lambda: len(targets()) == 1)
    split = tmux('split-window', '-d', '-t', pane, '-P', '-F', '#{pane_id}')
    tmux('select-layout', '-t', pane, 'even-vertical')
    start(split)
    wait('新規ペインのCodexを自動発見', lambda: len(targets()) == 2)
    self_hook = tmux('show-option', '-gqv', '@test_existing_hook')
    if self_hook != 'preserved':
        raise AssertionError('既存フック保持')
    print('PASS 既存フック保持', flush=True)
    results.append('既存フック保持')
    extras = []
    for number in range(9):
        extra = tmux('new-session', '-d', '-s', f'parallel-{number}', '-x', '160', '-y', '45', '-P', '-F', '#{pane_id}')
        extras.append(extra)
        start(extra)
    wait('11個のCodexを同時に自動発見', lambda: len(targets()) == 11, 40)
    wait('同一ディレクトリの11スレッドを区別', lambda: len({t['thread_id'] for t in targets() if t['thread_id']}) == 11, 40)
    tmux('kill-pane', '-t', split)
    wait('削除ペインの監視終了', lambda: len(targets()) == 10)
    tmux('kill-session', '-t', 'parallel-8')
    wait('削除セッションの監視終了', lambda: len(targets()) == 9)
    provider.mode = 'capacity'
    tmux('send-keys', '-t', pane, '-l', '/goal Perform the local recovery integration test until completed.')
    time.sleep(0.25)
    tmux('send-keys', '-t', pane, 'Enter')
    thread = wait('Goalのスレッドを確定', lambda: next((t['thread_id'] for t in targets() if t['pane_id'] == pane), None))
    wait('実際のCapacityエラーとblockedを検出', lambda: goal_status(thread) == 'blocked' and 'Goal stalled' in screen(pane), 45)
    provider.mode = 'success'
    wait('実際の/goal resumeでGoalがactiveへ変化', lambda: goal_status(thread) == 'active', 30)
    wait('復旧成功を別情報源と通知で確認', lambda: any('Codex Goal Resumed' in text for text in provider.webhooks), 30)
    provider.mode = 'capacity'
    wait('新しいターンのCapacity再発を検出', lambda: goal_status(thread) == 'blocked', 30)
    provider.mode = 'success'
    wait('Capacity再発後も再度復旧', lambda: sum('Codex Goal Resumed' in text for text in provider.webhooks) == 2 and goal_status(thread) == 'active', 30)
    if sum('Codex Capacity Error' in text for text in provider.webhooks) != 2:
        raise AssertionError('同じエラーを重複処理しない')
    results.append('同じエラーを重複処理しない')
    print('PASS 同じエラーを重複処理しない', flush=True)
    tmux('send-keys', '-t', pane, '-l', '/goal pause')
    time.sleep(0.25)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('ユーザーによるpause', lambda: goal_status(thread) == 'paused', 20)
    time.sleep(4)
    if goal_status(thread) != 'paused':
        raise AssertionError('pausedを自動再開しない')
    results.append('pausedを自動再開しない')
    print('PASS pausedを自動再開しない', flush=True)
    monitor.terminate()
    monitor.wait(timeout=10)
    codex_pid = next(t['pid'] for t in targets() if t['pane_id'] == pane)
    os.kill(codex_pid, 15)
    wait('テスト用Codexのみ終了', lambda: tmux('display-message', '-p', '-t', pane, '#{pane_current_command}') == 'zsh')
    launch = f'env -u CODEX_THREAD_ID CODEX_HOME={shlex.quote(str(codex_home))} codex --no-daemon --no-alt-screen -C {shlex.quote(str(root))} resume {thread}'
    tmux('send-keys', '-t', pane, '-l', launch)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('実際のResume goal確認画面', lambda: 'Resume paused goal?' in screen(pane), 30)
    import asyncio

    from monitor import adapter
    from monitor.processes import discover
    from monitor.recovery import recover
    from monitor.state import State
    from monitor.tmux import panes
    from monitor.tracking import Target
    with sqlite3.connect(codex_home / 'goals_1.sqlite') as db:
        db.execute("UPDATE thread_goals SET status='blocked',updated_at_ms=? WHERE thread_id=?", (int(time.time() * 1000), thread))
    current_pane = next(p for p in asyncio.run(panes(socket)) if p.pane == pane)
    current_process = next(p for p in discover() if p.tty == current_pane.tty)
    with sqlite3.connect(codex_home / 'state_5.sqlite') as db:
        rollout = Path(db.execute('SELECT rollout_path FROM threads WHERE id=?', (thread,)).fetchone()[0])
    target = Target(current_pane, current_process, os.pidfd_open(current_process.pid), thread=thread, rollout=rollout)
    target.recovery.phase = 'sent'
    target.recovery.deadline = time.time() + 20
    if not adapter.resume_selected(screen(pane)):
        raise AssertionError('Resume goalが選択されていることを確認')
    asyncio.run(recover(target, screen(pane), lambda *arguments: None, State(root / 'menu-state'), 3))
    os.close(target.pidfd)
    wait('確認画面のResume goalを選択してactiveを確認', lambda: goal_status(thread) == 'active')
    tmux('send-keys', '-t', pane, '-l', '/goal pause')
    time.sleep(0.25)
    tmux('send-keys', '-t', pane, 'Enter')
    wait('確認画面の検証後にpause', lambda: goal_status(thread) == 'paused')
    monitor = subprocess.Popen(['/usr/bin/python3', '-m', 'monitor.service', '--config', str(monitor_config)], cwd=project, env=monitor_env, stdout=log, stderr=log)
    time.sleep(1)
    monitor.terminate()
    monitor.wait(timeout=10)
    monitor = subprocess.Popen(['/usr/bin/python3', str(project / 'tests/monitor_errorless.py'), '--config', str(monitor_config)], cwd=project, env=monitor_env, stdout=log, stderr=log)
    provider.mode = 'capacity'
    errorless_pane = extras[0]
    errorless_thread = next(t['thread_id'] for t in targets() if t['pane_id'] == errorless_pane)
    tmux('send-keys', '-t', errorless_pane, '-l', '/goal Perform the isolated TUI capacity detection test.')
    time.sleep(0.25)
    tmux('send-keys', '-t', errorless_pane, 'Enter')
    wait('Capacity情報のない実行履歴でstalledを検出', lambda: goal_status(errorless_thread) == 'blocked' and 'Goal stalled' in screen(errorless_pane))
    provider.mode = 'success'
    wait('TUIだけのCapacity情報から実際に復旧', lambda: goal_status(errorless_thread) == 'active' and any('Codex Goal Resumed' in text and errorless_thread in text for text in provider.webhooks), 30)
    tmux('send-keys', '-t', errorless_pane, '-l', '/goal pause')
    time.sleep(0.25)
    tmux('send-keys', '-t', errorless_pane, 'Enter')
    wait('TUIだけの検証後にpause', lambda: goal_status(errorless_thread) == 'paused')
    monitor.terminate()
    monitor.wait(timeout=10)
    monitor = subprocess.Popen(['/usr/bin/python3', '-m', 'monitor.service', '--config', str(monitor_config)], cwd=project, env=monitor_env, stdout=log, stderr=log)
    with sqlite3.connect(codex_home / 'goals_1.sqlite') as db:
        db.execute("UPDATE thread_goals SET status='complete',updated_at_ms=? WHERE thread_id=?", (int(time.time() * 1000), thread))
    wait('completeのGoalは通知のみ', lambda: any('Codex Goal Completed' in text for text in provider.webhooks))
    time.sleep(3)
    if goal_status(thread) != 'complete':
        raise AssertionError('completeを自動再開しない')
    print('PASS completeを自動再開しない', flush=True)
    results.append('completeを自動再開しない')
    original_pipe = root / 'existing-pipe.log'
    tmux('pipe-pane', '-t', extras[0], f'cat >> {shlex.quote(str(original_pipe))}')
    monitor.terminate()
    monitor.wait(timeout=10)
    monitor = subprocess.Popen(['/usr/bin/python3', '-m', 'monitor.service', '--config', str(monitor_config)], cwd=project, env=monitor_env, stdout=log, stderr=log)
    time.sleep(2)
    if tmux('display-message', '-p', '-t', extras[0], '#{pane_pipe}') != '1':
        raise AssertionError('既存pipe-pane保持')
    results.append('既存pipe-pane保持')
    print('PASS 既存pipe-pane保持', flush=True)
    before = {t['pane_id']: t['pid'] for t in targets()}
    monitor.terminate()
    monitor.wait(timeout=10)
    monitor = subprocess.Popen(['/usr/bin/python3', '-m', 'monitor.service', '--config', str(monitor_config)], cwd=project, env=monitor_env, stdout=log, stderr=log)
    wait('監視再起動後にCodexを再起動せず再発見', lambda: {t['pane_id']: t['pid'] for t in targets()} == before)
    tmux('kill-server')
    wait('tmuxサーバー終了を検出', lambda: len(targets()) == 0)
    new = tmux('new-session', '-d', '-s', 'restarted', '-x', '160', '-y', '45', '-P', '-F', '#{pane_id}')
    start(new)
    wait('tmuxサーバー再起動後に自動再発見', lambda: len(targets()) == 1)
    (root / 'results.json').write_text(json.dumps({'passed': results, 'webhooks': provider.webhooks}, ensure_ascii=False, indent=2))
finally:
    monitor.terminate()
    monitor.wait(timeout=10)
    subprocess.run(['tmux', '-S', str(socket), 'kill-server'], check=False, stderr=subprocess.DEVNULL)
    provider.shutdown()
    log.close()
