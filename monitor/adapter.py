import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

CAPACITY = 'Selected model is at capacity. Please try a different model.'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


@dataclass(frozen=True)
class Goal:
    goal_id: str
    status: str
    updated: int
    tokens: int
    created: int


def read_goal(home: Path, thread: str) -> Goal | None:
    try:
        with sqlite3.connect(f'file:{home}/goals_1.sqlite?mode=ro', uri=True, timeout=0.1) as db:
            row = db.execute('SELECT goal_id,status,updated_at_ms,tokens_used,created_at_ms FROM thread_goals WHERE thread_id=?', (thread,)).fetchone()
        return Goal(*row) if row else None
    except sqlite3.Error:
        return None


def resolve_title(home: Path, title: str) -> tuple[str, Path] | None:
    # Codex 0.162.1 truncates terminal-title items to 32 characters.
    match = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{5,12})', title)
    if not match:
        return None
    prefix = match.group(1)
    try:
        with sqlite3.connect(f'file:{home}/state_5.sqlite?mode=ro', uri=True, timeout=0.1) as db:
            rows = db.execute('SELECT id,rollout_path FROM threads WHERE id GLOB ?', (prefix + '*',)).fetchall()
        if len(rows) == 1:
            return rows[0][0], Path(rows[0][1])
    except sqlite3.Error:
        pass
    return None


def resolve_session(home: Path, thread: str) -> tuple[str, Path] | None:
    if not UUID.fullmatch(thread):
        return None
    try:
        with sqlite3.connect(f'file:{home}/state_5.sqlite?mode=ro', uri=True, timeout=0.1) as db:
            row = db.execute('SELECT rollout_path FROM threads WHERE id=?', (thread,)).fetchone()
        if row:
            return thread, Path(row[0])
    except sqlite3.Error:
        pass
    return None


def status_thread(screen: str) -> str | None:
    lines = screen.splitlines()
    positions = [index for index, line in enumerate(lines) if re.match(r'^[\s│]*Session:', line)]
    if not positions:
        return None
    index = positions[-1]
    text = lines[index].split('Session:', 1)[1] + ''.join(lines[index + 1:index + 3])
    value = ''.join(text.replace('│', '').split())[:36]
    return value if UUID.fullmatch(value) else None


def event(line: bytes) -> tuple[str, str | None]:
    try:
        record = json.loads(line)
        payload = record.get('payload', {})
        if record.get('type') != 'event_msg':
            return '', None
        kind = payload.get('type', '')
        error = payload.get('error') or {}
        info = error.get('codex_error_info') if isinstance(error, dict) else None
        overloaded = info == 'server_overloaded' or isinstance(info, dict) and 'server_overloaded' in info
        if overloaded or kind == 'error' and payload.get('codex_error_info') == 'server_overloaded':
            return 'capacity', payload.get('turn_id')
        if kind in ('task_started', 'turn_started'):
            return 'started', payload.get('turn_id')
        if kind in ('task_complete', 'turn_complete', 'turn_aborted'):
            return 'ended', payload.get('turn_id')
        if kind == 'user_message':
            return 'user', None
    except (ValueError, AttributeError, TypeError):
        pass
    return '', None


def empty_composer(screen: str, cursor_x: int, cursor_y: int) -> bool:
    lines = screen.splitlines()
    if not 0 <= cursor_y < len(lines) or cursor_x != 2:
        return False
    line = lines[cursor_y].strip()
    if not line.startswith('›'):
        return False
    text = line[1:].strip()
    return text in ('', 'Ask Codex to do anything')


def idle_stalled(screen: str, cursor_x: int, cursor_y: int) -> bool:
    return any('Goal stalled (/goal resume)' in line for line in screen.splitlines()[cursor_y + 1:cursor_y + 6]) and empty_composer(screen, cursor_x, cursor_y) and 'esc to interrupt' not in screen.lower()


def status_idle(screen: str, cursor_x: int, cursor_y: int) -> bool:
    footer = screen.splitlines()[cursor_y + 1:cursor_y + 6]
    return any(any(state in line for state in ('Goal stalled (/goal resume)', 'Goal achieved', 'Goal hit usage limits')) for line in footer) and empty_composer(screen, cursor_x, cursor_y) and 'esc to interrupt' not in screen.lower()


def terminal_capacity(screen: str, cursor_y: int) -> bool:
    lines = screen.splitlines()
    before = [line.strip() for line in lines[:cursor_y] if line.strip() and not re.fullmatch(r'[─━\s]+', line)]
    tail = ' '.join(before[-4:])
    return tail.endswith(CAPACITY) and ('■ ' + CAPACITY in tail or 'Error: ' + CAPACITY in tail)


def resume_selected(screen: str) -> bool:
    return 'Resume paused goal?' in screen and bool(re.search(r'[›❯>]\s*(?:1[.)]\s*)?Resume goal\b', screen)) and 'Leave paused' in screen
