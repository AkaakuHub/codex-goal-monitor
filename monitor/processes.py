import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    start: str
    tty: str
    home: Path


def read_process(pid: int) -> Process | None:
    root = Path('/proc') / str(pid)
    try:
        if root.stat().st_uid != os.getuid() or Path(os.readlink(root / 'exe')).name != 'codex':
            return None
        fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
        env = dict(item.split('=', 1) for item in (root / 'environ').read_bytes().decode(errors='replace').split('\0') if '=' in item)
        return Process(pid, int(fields[1]), fields[19], os.readlink(root / 'fd/0'), Path(env.get('CODEX_HOME', str(Path.home() / '.codex'))))
    except (OSError, ValueError):
        return None


def discover() -> list[Process]:
    return [process for entry in Path('/proc').iterdir() if entry.name.isdigit() and (process := read_process(int(entry.name)))]


def descendant(pid: int, root: int) -> bool:
    visited: set[int] = set()
    while pid > 1 and pid not in visited:
        if pid == root:
            return True
        visited.add(pid)
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            pid = int(fields[1])
        except (OSError, ValueError):
            return False
    return False


def session_fds(process: Process) -> set[Path]:
    result: set[Path] = set()
    try:
        for fd in Path(f'/proc/{process.pid}/fd').iterdir():
            try:
                path = Path(os.readlink(fd))
                if path.suffix == '.jsonl' and process.home / 'sessions' in path.parents:
                    result.add(path)
            except OSError:
                pass
    except OSError:
        pass
    return result
