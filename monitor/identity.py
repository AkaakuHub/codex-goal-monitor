import asyncio
import re
import time
from pathlib import Path

from . import adapter, tmux
from .input import send_command
from .processes import read_process
from .tracking import Target


def stable_title(title: str) -> str:
    return re.sub(r'^[\u2800-\u28ff]\s*', '', title)


async def inspect_thread(target: Target, expected: str | None = None) -> tuple[str, Path] | None:
    if not await send_command(target, '/status'):
        return None
    await asyncio.sleep(0.35)
    panes = await tmux.panes(target.pane.socket)
    pane = next((p for p in panes if p.pane == target.pane.pane), None)
    if not pane or read_process(target.process.pid) != target.process:
        return None
    _, screen = await tmux.command(pane.socket, 'capture-pane', '-p', '-t', pane.pane)
    if not adapter.status_idle(screen, pane.cursor_x, pane.cursor_y):
        return None
    thread = adapter.status_thread(screen)
    if not thread or expected and thread != expected:
        return None
    identity = adapter.resolve_session(target.process.home, thread)
    if not identity:
        return None
    target.proof_title = stable_title(pane.title)
    target.proof_at = time.time()
    target.pane = pane
    return identity
