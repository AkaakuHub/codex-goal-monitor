import asyncio
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pane:
    socket: Path
    pane: str
    session: str
    window: str
    index: str
    pid: int
    tty: str
    title: str
    piped: bool
    cursor_x: int
    cursor_y: int
    mode: bool

    @property
    def key(self) -> str:
        return f'{self.socket}:{self.pane}'

    @property
    def label(self) -> str:
        return f'{self.session}:{self.window}.{self.index} ({self.pane}; socket={self.socket.name})'


async def command(socket: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec('tmux', '-S', str(socket), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 5)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, ''
    return proc.returncode or 0, out.decode(errors='replace')


async def panes(socket: Path) -> list[Pane]:
    fields = ('pane_id', 'session_name', 'window_index', 'pane_index', 'pane_pid', 'pane_tty', 'pane_title', 'pane_pipe', 'cursor_x', 'cursor_y', 'pane_in_mode')
    code, output = await command(socket, 'list-panes', '-a', '-F', '\t'.join('#{' + name + '}' for name in fields))
    result: list[Pane] = []
    if code:
        return result
    for line in output.splitlines():
        values = line.split('\t')
        if len(values) == len(fields):
            try:
                result.append(Pane(socket, *values[:4], int(values[4]), *values[5:7], bool(int(values[7])), int(values[8]), int(values[9]), bool(int(values[10]))))
            except ValueError:
                pass
    return result


class Server:
    def __init__(self, socket: Path, helper: Path, events: Path, wake: Callable[[], None], output: Callable[[str], None]):
        self.socket = socket
        self.helper = helper
        self.events = events
        self.wake = wake
        self.output = output
        self.subscriptions: set[str] = set()
        self.process: asyncio.subprocess.Process | None = None
        self.hooks: list[str] = []
        self.task: asyncio.Task[None] | None = None

    async def start(self, session: str) -> None:
        _, hook_list = await command(self.socket, 'show-hooks', '-g')
        available = {line.split('[', 1)[0].split(' ', 1)[0] for line in hook_list.splitlines()}
        for name in ('session-created', 'session-closed', 'after-new-window', 'after-split-window', 'after-kill-pane', 'window-linked', 'window-unlinked'):
            if name not in available:
                continue
            hook = f'{name}[9471]'
            code, existing = await command(self.socket, 'show-hooks', '-g', hook)
            indexed = next((line for line in existing.splitlines() if line.startswith(hook + ' ')), '')
            if not code and indexed[len(hook):].strip() and str(self.helper) not in indexed:
                continue
            call = ' '.join(shlex.quote(str(s)) for s in (self.helper, self.events, 'discovery'))
            code, _ = await command(self.socket, 'set-hook', '-g', hook, f'run-shell -b {shlex.quote(call)}')
            if not code:
                self.hooks.append(hook)
        self.process = await asyncio.create_subprocess_exec('tmux', '-S', str(self.socket), '-C', 'attach-session', '-f', 'no-output,ignore-size,read-only', '-t', session, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024)
        if self.process.stdin:
            self.process.stdin.write(b'refresh-client -B "codex:%*:#{pane_current_command}"\n')
            await self.process.stdin.drain()
        self.task = asyncio.create_task(self.listen())

    async def subscribe(self, pane: str) -> None:
        if pane in self.subscriptions or not self.process or not self.process.stdin:
            return
        name = 'goal-' + pane[1:]
        value = f'{name}:{pane}:#{{C:*Selected model is at capacity.*}}|#{{C:*Goal stalled*}}|#{{C:*Pursuing goal*}}|#{{C:*Resume paused goal?*}}|#{{C:*Goal achieved*}}|#{{C:*Goal hit usage limits*}}|#{{C:*esc to interrupt*}}|#{{pane_title}}|#{{cursor_x}}|#{{cursor_y}}|#{{cursor_flag}}'
        self.process.stdin.write(('refresh-client -B ' + shlex.quote(value) + '\n').encode())
        await self.process.stdin.drain()
        self.subscriptions.add(pane)

    def unsubscribe(self, pane: str) -> None:
        if pane in self.subscriptions and self.process and self.process.stdin and self.process.returncode is None:
            self.process.stdin.write(f'refresh-client -B goal-{pane[1:]}\n'.encode())
        self.subscriptions.discard(pane)

    async def listen(self) -> None:
        if not self.process or not self.process.stdout:
            return
        async for line in self.process.stdout:
            if line.startswith(b'%subscription-changed goal-'):
                name = line.split(b' ', 2)[1].decode()
                self.output('%' + name.removeprefix('goal-'))
                continue
            if line.startswith((b'%session', b'%window', b'%layout', b'%subscription', b'%exit')):
                self.wake()
        self.wake()

    async def close(self) -> None:
        for hook in self.hooks:
            _, existing = await command(self.socket, 'show-hooks', '-g', hook)
            indexed = next((line for line in existing.splitlines() if line.startswith(hook + ' ')), '')
            if str(self.helper) in indexed:
                await command(self.socket, 'set-hook', '-gu', hook)
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()
