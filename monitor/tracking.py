import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import adapter
from .policy import Recovery, capacity_for_goal
from .processes import Process, session_fds
from .tmux import Pane


@dataclass
class Target:
    pane: Pane
    process: Process
    pidfd: int
    thread: str | None = None
    rollout: Path | None = None
    offset: int = 0
    partial: bytes = b''
    status: str = ''
    recovery: Recovery = field(default_factory=Recovery)
    capture_due: bool = True
    pending_capacity: str | None = None
    uncertain_notified: bool = False
    last_goal_id: str = ''
    turn_id: str | None = None
    proof_title: str = ''
    proof_at: float = 0

    def bind(self, thread: str, rollout: Path, recovery: Recovery) -> None:
        if thread == self.thread and rollout == self.rollout:
            return
        self.thread = thread
        self.rollout = rollout
        self.recovery = recovery
        self.offset = 0
        self.partial = b''
        self.status = ''
        errors = self.replay(initial=True)
        self.pending_capacity = errors[-1] if errors else None

    def replay(self, initial: bool = False) -> list[str]:
        errors: list[str] = []
        if not self.rollout:
            return errors
        goal = adapter.read_goal(self.process.home, self.thread or '')
        try:
            with self.rollout.open('rb') as source:
                if self.rollout.stat().st_size < self.offset:
                    self.offset = 0
                    self.partial = b''
                source.seek(self.offset)
                while chunk := source.read(1024 * 1024):
                    self.offset += len(chunk)
                    lines = (self.partial + chunk).split(b'\n')
                    self.partial = lines.pop()
                    for line in lines:
                        kind, turn = adapter.event(line)
                        if turn:
                            self.turn_id = turn
                        if kind == 'started':
                            errors.clear()
                            if self.recovery.phase == 'watching':
                                self.recovery.cancel()
                            self.recovery.busy = True
                            self.recovery.started = True
                        elif kind == 'ended':
                            self.recovery.busy = False
                        elif kind == 'user':
                            errors.clear()
                            if not initial:
                                self.recovery.cancel()
                        elif kind == 'capacity':
                            self.recovery.busy = False
                            identity = f'turn:{turn or hashlib.sha256(line).hexdigest()}'
                            try:
                                timestamp = json.loads(line).get('timestamp', '')
                                from datetime import datetime
                                occurred = datetime.fromisoformat(timestamp).timestamp()
                                recent = capacity_for_goal(occurred, time.time(), goal.created if goal else None)
                            except (ValueError, TypeError):
                                recent = False
                            if recent:
                                errors.append(identity)
        except OSError:
            pass
        return errors


def binding(process: Process, pane: Pane) -> tuple[str, Path] | None:
    identity = adapter.resolve_title(process.home, pane.title)
    if identity:
        return identity
    paths = session_fds(process)
    if len(paths) != 1:
        return None
    path = paths.pop()
    try:
        with path.open('rb') as source:
            metadata = json.loads(source.readline())
        thread = metadata.get('payload', {}).get('id')
        if isinstance(thread, str) and adapter.UUID.fullmatch(thread):
            return thread, path
    except (OSError, ValueError):
        pass
    return None
