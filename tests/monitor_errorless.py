import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor import adapter
from monitor.service import main

parse = adapter.event


def event_without_capacity(line: bytes) -> tuple[str, str | None]:
    kind, turn = parse(line)
    return ('ended', turn) if kind == 'capacity' else (kind, turn)


adapter.event = event_without_capacity
main()
