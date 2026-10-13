import asyncio

from . import adapter, tmux
from .processes import read_process
from .tracking import Target


async def send_command(target: Target, text: str, goal: adapter.Goal | None = None) -> bool:
    panes = await tmux.panes(target.pane.socket)
    pane = next((p for p in panes if p.pane == target.pane.pane), None)
    if not pane or pane.mode or read_process(target.process.pid) != target.process:
        return False
    _, screen = await tmux.command(pane.socket, 'capture-pane', '-p', '-t', pane.pane)
    ready = adapter.status_idle if text == '/status' else adapter.idle_stalled
    if not ready(screen, pane.cursor_x, pane.cursor_y):
        return False
    code, _ = await tmux.command(pane.socket, 'send-keys', '-t', pane.pane, '-l', text)
    if code:
        return False
    await asyncio.sleep(0.25)
    refreshed = await tmux.panes(pane.socket)
    current = next((p for p in refreshed if p.pane == pane.pane), None)
    _, typed = await tmux.command(pane.socket, 'capture-pane', '-p', '-t', pane.pane)
    lines = typed.splitlines()
    if not current or current.mode or current.cursor_y >= len(lines) or lines[current.cursor_y].strip() != '› ' + text or current.cursor_x != len(text) + 2 or read_process(target.process.pid) != target.process:
        return False
    if goal:
        latest = adapter.read_goal(target.process.home, target.thread or '')
        if not latest or latest.goal_id != goal.goal_id or latest.status != 'blocked':
            return False
    code, _ = await tmux.command(pane.socket, 'send-keys', '-t', pane.pane, 'Enter')
    return not code
