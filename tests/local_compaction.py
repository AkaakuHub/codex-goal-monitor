import argparse
import json
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from local_provider import Provider

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor.processes import discover


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    root = parser.parse_args().directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    home = root / 'home'
    home.mkdir(exist_ok=True)
    socket = root / 'tmux.sock'
    provider = Provider()
    provider.mode = 'success'
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
[model_providers.local_test.capabilities]
remote_compaction = "v2"
[projects.{json.dumps(str(root))}]
trust_level = "trusted"
''')
    results = []

    def tmux(*args):
        return subprocess.check_output(['tmux', '-S', str(socket), *args], stderr=subprocess.DEVNULL).decode().strip()

    def wait(label, condition, timeout=40):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if condition():
                    results.append(label)
                    print('PASS', label, flush=True)
                    return
            except (OSError, sqlite3.Error):
                pass
            time.sleep(0.15)
        raise AssertionError(label)

    def send(text):
        tmux('send-keys', '-t', pane, '-l', text)
        time.sleep(0.3)
        tmux('send-keys', '-t', pane, 'Enter')

    def session():
        with sqlite3.connect(home / 'state_5.sqlite') as db:
            return db.execute('select id,rollout_path from threads order by created_at desc limit 1').fetchone()

    try:
        pane = tmux('new-session', '-d', '-s', 'compact-test', '-x', '160', '-y', '45', '-P', '-F', '#{pane_id}')
        launch = f'env -u CODEX_THREAD_ID CODEX_HOME={shlex.quote(str(home))} codex --no-daemon --no-alt-screen -C {shlex.quote(str(root))}'
        send(launch + ' "Local compaction test only."')
        wait('隔離したCodexの最初のターンが終了', lambda: 'Local test completed.' in tmux('capture-pane', '-p', '-t', pane))
        thread, path = session()
        provider.mode = 'stream'
        send('/compact')
        wait('実際のremote compact通信エラーを再現', lambda: 'Error running remote compact task:' in tmux('capture-pane', '-p', '-t', pane))
        send('/quit')
        wait('隔離したCLIが終了', lambda: tmux('display-message', '-p', '-t', pane, '#{pane_current_command}') == 'zsh')
        provider.mode = 'success'
        send(launch + ' -c ' + shlex.quote('model_providers.local_test.capabilities.remote_compaction="unsupported"') + ' resume ' + thread)
        wait('同じthreadを再起動', lambda: any(p.tty == tmux('display-message', '-p', '-t', pane, '#{pane_tty}') and p.home == home for p in discover()))
        time.sleep(1)
        before = Path(path).stat().st_size
        send('/compact')
        def compacted():
            with Path(path).open('rb') as file:
                file.seek(before)
                return any(json.loads(line).get('type') == 'compacted' for line in file if line.endswith(b'\n'))
        wait('通常モデルの要約経路でcompactedを確認', compacted)
        (root / 'results.json').write_text(json.dumps({'passed': results, 'thread_unchanged': session()[0] == thread}, ensure_ascii=False, indent=2))
    finally:
        subprocess.run(['tmux', '-S', str(socket), 'kill-server'], stderr=subprocess.DEVNULL, check=False)
        provider.shutdown()


if __name__ == '__main__':
    main()
