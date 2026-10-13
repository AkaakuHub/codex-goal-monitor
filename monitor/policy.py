from dataclasses import dataclass, field


def capacity_for_goal(occurred: float, now: float, goal_created: int | None) -> bool:
    return goal_created is not None and occurred * 1000 >= goal_created and 0 <= now - occurred <= 1800


@dataclass
class Recovery:
    seen: set[str] = field(default_factory=set)
    error: str | None = None
    error_time: float = 0
    attempt: int = 0
    due: float = 0
    failures: int = 0
    halted: bool = False
    phase: str = 'watching'
    deadline: float = 0
    goal_id: str = ''
    started: bool = False
    busy: bool = False
    resumes: int = 0
    progressed: bool = False
    token_baseline: int = 0
    wasted_turns: int = 0

    def capacity(self, identity: str, now: float, delays: list[float]) -> bool:
        if identity in self.seen or self.halted:
            return False
        self.seen.add(identity)
        self.error = identity
        self.error_time = now
        self.due = now + delays[min(self.attempt, len(delays) - 1)]
        self.attempt += 1
        return True

    def failed_turn(self, tokens: int, new_work: bool) -> None:
        if new_work:
            self.wasted_turns = 0
        elif self.resumes and tokens > self.token_baseline:
            self.wasted_turns += 1
        self.token_baseline = tokens

    def eligible(self, status: str, goal_id: str, now: float) -> bool:
        return status == 'blocked' and self.error is not None and not self.halted and self.phase == 'watching' and now >= self.due and now - self.error_time <= 1800 and (not self.goal_id or self.goal_id == goal_id)

    def cancel(self) -> None:
        self.error = None
        self.phase = 'watching'
        self.progressed = False

    def success(self) -> None:
        self.cancel()
        self.attempt = 0
        self.failures = 0
        self.resumes = 0
        self.wasted_turns = 0
