import re
from dataclasses import dataclass

DELAYS = (30, 60, 120, 300, 600)


@dataclass(frozen=True)
class Goal:
    status: str
    created: int
    objective: str
    tokens: int

    @property
    def identity(self) -> tuple[int, str]:
        return self.created, self.objective

    @classmethod
    def parse(cls, data: dict[str, object]) -> 'Goal':
        status, created, objective, tokens = (data.get(k) for k in ('status', 'createdAt', 'objective', 'tokensUsed'))
        if not isinstance(status, str) or not isinstance(created, int) or not isinstance(objective, str) or not isinstance(tokens, int):
            raise ValueError('Invalid goal')
        return cls(status, created, objective, tokens)


def retryable(turn: dict[str, object], goal: Goal, now: float) -> bool:
    started = turn.get('startedAt')
    error = turn.get('error')
    if turn.get('status') != 'failed' or not isinstance(error, dict) or not isinstance(started, int):
        return False
    if not goal.created <= started <= now or now - started > 1800:
        return False
    info = error.get('codexErrorInfo')
    if info in ('serverOverloaded', 'rateLimitExceeded', 'responseStreamDisconnected', 'responseStreamConnectionFailed'):
        return True
    if isinstance(info, dict) and any(
        name in ('responseStreamDisconnected', 'responseStreamConnectionFailed')
        or isinstance(value, dict) and value.get('httpStatusCode') == 429
        for name, value in info.items()
    ):
        return True
    message = error.get('message', '')
    return isinstance(message, str) and (
        message.startswith(('stream disconnected before completion:', 'Error running remote compact task: stream disconnected before completion:'))
        or bool(re.search(r'\b(?:HTTP\s*)?429\b', message))
    )


@dataclass
class Recovery:
    attempt: int = 0
    last_turn: str = ''
    due: float = 0
    error_time: float = 0
    phase: str = 'watching'
    baseline: int = 0
    wasted: int = 0

    def schedule(self, turn: dict[str, object], goal: Goal, now: float) -> bool:
        identifier = turn.get('id')
        if self.phase == 'halted' or goal.status != 'blocked' or not isinstance(identifier, str) or identifier == self.last_turn or not retryable(turn, goal, now):
            return False
        if self.attempt and goal.tokens > self.baseline:
            self.wasted += 1
        self.last_turn = identifier
        self.baseline = goal.tokens
        self.error_time = now
        if self.wasted >= 5:
            self.phase = 'halted'
            return False
        self.due = now + DELAYS[min(self.attempt, len(DELAYS) - 1)]
        self.attempt += 1
        self.phase = 'waiting'
        return True

    def eligible(self, goal: Goal, now: float) -> bool:
        return self.phase == 'waiting' and goal.status == 'blocked' and self.due <= now <= self.error_time + 1800

    def cancel(self) -> None:
        self.phase = 'watching'

    def complete(self, turn: dict[str, object]) -> bool:
        if self.phase not in ('sent', 'verifying') or turn.get('id') == self.last_turn or turn.get('status') != 'completed':
            return False
        self.phase = 'watching'
        self.attempt = 0
        self.wasted = 0
        return True
