import json
import os
from dataclasses import asdict
from pathlib import Path

from .policy import Recovery


class State:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'recovery.json'
        self.values: dict[str, Recovery] = {}
        self.cached: dict[Path, str] = {}
        if self.path.exists():
            records = json.loads(self.path.read_text())
            for key, value in records.items():
                value['seen'] = set(value['seen'])
                self.values[key] = Recovery(**value)

    def get(self, key: str) -> Recovery:
        return self.values.setdefault(key, Recovery())

    def save(self) -> None:
        values = {key: {**asdict(value), 'seen': sorted(value.seen)} for key, value in self.values.items()}
        self.write(self.path, values)

    def status(self, values: list[dict[str, str | int | bool | None]]) -> None:
        self.write(self.directory / 'status.json', values)

    def write(self, path: Path, value: object) -> None:
        serialized = json.dumps(value, ensure_ascii=False, indent=2)
        if self.cached.get(path) == serialized:
            return
        temporary = path.with_suffix('.new')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        self.cached[path] = serialized
