import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

project = Path(__file__).resolve().parents[1]
account = Path.home()
directory = account / '.config/codex-goal-monitor'
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
configuration = directory / 'config.toml'
environment = directory / 'monitor.env'
if not environment.exists():
    webhook = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not re.fullmatch(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/[0-9]+/[A-Za-z0-9_-]+', webhook):
        raise SystemExit('環境変数DISCORD_WEBHOOK_URLにDiscord WebhookのURLを設定してください')
    fd = os.open(environment, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(f'DISCORD_WEBHOOK_URL={webhook}\n')
binary = account / '.local/lib/codex-goal-monitor/events'
binary.parent.mkdir(parents=True, exist_ok=True)
compiled = binary.with_suffix('.new')
subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', str(project / 'native/events.c'), '-o', str(compiled)], check=True)
os.replace(compiled, binary)
if not configuration.exists():
    values = {
        'runtime': f'/run/user/{os.getuid()}/codex-goal-monitor',
        'state': str(account / '.local/state/codex-goal-monitor'),
        'helper': str(binary),
        'socket_directories': [f'/tmp/tmux-{os.getuid()}'],
        'sockets': [],
        'codex_homes': [str(account / '.codex')],
        'retry_delays': [30, 60, 120, 300, 600],
        'max_failures': 3,
    }
    fd = os.open(configuration, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write('\n'.join(f'{key} = {json.dumps(value)}' for key, value in values.items()) + '\n')
codex_config = account / '.codex/config.toml'
codex_config.parent.mkdir(parents=True, exist_ok=True)
original = codex_config.read_text() if codex_config.exists() else ''
config = tomllib.loads(original)
if config.get('tui', {}).get('terminal_title') != ['session-id']:
    backup = directory / 'codex-config.before-monitor.toml'
    if not backup.exists():
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(original)
    section = re.search(r'^\[tui\]\s*\n', original, re.MULTILINE)
    if not section:
        original += '\n[tui]\n'
        section = re.search(r'^\[tui\]\s*\n', original, re.MULTILINE)
    end = re.search(r'^\[', original[section.end():], re.MULTILINE)
    stop = section.end() + end.start() if end else len(original)
    body = original[section.end():stop]
    if re.search(r'^terminal_title\s*=', body, re.MULTILINE):
        body = re.sub(r'^terminal_title\s*=.*$', 'terminal_title = ["session-id"]', body, flags=re.MULTILINE)
    else:
        body = 'terminal_title = ["session-id"]\n' + body
    updated = original[:section.end()] + body + original[stop:]
    tomllib.loads(updated)
    codex_config.write_text(updated)
service = account / '.config/systemd/user/codex-goal-monitor.service'
service.parent.mkdir(parents=True, exist_ok=True)
project_directory = str(project).replace('%', '%%')
service.write_text((project / 'deploy/codex-goal-monitor.service').read_text().replace('@PROJECT_DIRECTORY@', project_directory))
print(f'サービス: {service}')
print(f'設定: {configuration} (600)')
print(f'環境変数: {environment} (600)')
print(f'tmuxイベント通知: {binary}')
