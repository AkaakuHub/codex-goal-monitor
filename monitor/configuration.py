import json
import os
import re
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_path

WEBHOOK = re.compile(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/[0-9]+/[A-Za-z0-9_-]+')


@dataclass(frozen=True)
class Settings:
    webhook_url: str = ''
    sender_label: str = field(default_factory=socket.gethostname)
    codex_home: str = field(default_factory=lambda: os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    codex_command: str = 'codex'

    def validate(self) -> None:
        if not WEBHOOK.fullmatch(self.webhook_url):
            raise ValueError('Discord Webhook URLを正しく入力してください。')
        if not self.sender_label.strip() or len(self.sender_label) > 80:
            raise ValueError('送信元ラベルは1〜80文字で入力してください。')
        if not Path(self.codex_home).is_absolute():
            raise ValueError('Codexホームは絶対パスで指定してください。')
        if not self.codex_command.strip():
            raise ValueError('Codex CLIのコマンドまたは実行ファイルのパスを指定してください。')


def config_path() -> Path:
    return user_config_path('codex-goal-monitor', appauthor=False) / 'settings.json'


def load(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    values = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(values, dict) or any(not isinstance(v, str) for v in values.values()):
        raise ValueError('設定ファイルの値は文字列で指定してください。')
    return Settings(**values)


def save(path: Path, settings: Settings) -> None:
    settings.validate()
    if path.exists() and load(path) == settings:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(asdict(settings), output, ensure_ascii=False, indent=2)
        output.flush()
    os.replace(temporary, path)
