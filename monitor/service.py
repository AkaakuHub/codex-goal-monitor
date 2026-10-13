import asyncio
import logging
import os
import signal
import socket
import time
import tomllib
from pathlib import Path

from . import adapter, tmux
from .discovery import reconcile
from .evaluation import evaluate
from .inotify import Inotify
from .notifications import Notifications
from .state import State
from .tracking import Target

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, config: dict[str, object]):
        self.config = config
        self.runtime = Path(str(config['runtime']))
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.event_path = self.runtime / 'events.sock'
        self.event_path.unlink(missing_ok=True)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        self.socket.bind(str(self.event_path))
        os.chmod(self.event_path, 0o600)
        self.state = State(Path(str(config['state'])))
        self.helper = Path(str(config['helper']))
        self.notifications = Notifications(os.environ['DISCORD_WEBHOOK_URL'])
        self.servers: dict[Path, tmux.Server] = {}
        self.targets: dict[str, Target] = {}
        self.homes = {Path(str(p)) for p in config.get('codex_homes', [str(Path.home() / '.codex')])}
        self.directories = {Path(str(p)) for p in config.get('socket_directories', [f'/tmp/tmux-{os.getuid()}'])}
        self.explicit = {Path(str(p)) for p in config.get('sockets', [])}
        self.changed = asyncio.Event()
        self.stop = asyncio.Event()
        self.scan = True
        self.inotify = Inotify(self.filesystem)
        self.delays = [float(p) for p in config.get('retry_delays', [30, 60, 120, 300, 600])]

    def wake(self, scan: bool = True) -> None:
        self.scan = self.scan or scan
        self.changed.set()

    def filesystem(self, path: Path, mask: int) -> None:
        if mask & 0x4000:
            logger.warning('inotifyキューが溢れたため監視対象を再探索します')
            self.wake()
        elif any(path == p or p in path.parents for p in self.directories | {p.parent for p in self.explicit}) or mask & (0x100 | 0x80) and (path.suffix == '.jsonl' or path.is_dir()):
            self.wake()
        elif 'sessions' in path.parts or path.name.startswith('goals_1.sqlite'):
            self.wake(False)

    def datagrams(self) -> None:
        while True:
            try:
                data = self.socket.recv(4096).decode()
            except BlockingIOError:
                break
            if data == 'discovery':
                self.wake()

    def output(self, server_socket: Path, pane: str) -> None:
        target = self.targets.get(f'{server_socket}:{pane}')
        if target:
            target.capture_due = True
            self.wake(False)

    def notify(self, target: Target, title: str, action: str = '') -> None:
        goal = adapter.read_goal(target.process.home, target.thread or '')
        status = goal.status if goal else 'unknown'
        content = f'{title}\nServer: {socket.gethostname()}\ntmux: {target.pane.label}\nThread: {target.thread or "unknown"}\nGoal: {status}'
        if action:
            content += '\n' + action
        self.notifications.send(content)
        logger.info('%s pane=%s thread=%s goal=%s', title, target.pane.label, target.thread or 'unknown', status)

    def watch_home(self, home: Path) -> None:
        self.homes.add(home)
        self.inotify.add(home)
        self.inotify.add(home / 'sessions', recursive=True)


    def remove(self, key: str) -> None:
        target = self.targets.pop(key)
        server = self.servers.get(target.pane.socket)
        if server:
            server.unsubscribe(target.pane.pane)
        asyncio.get_running_loop().remove_reader(target.pidfd)
        os.close(target.pidfd)
        logger.info('Codexを監視対象から除外 pane=%s', target.pane.label)


    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        loop.add_reader(self.inotify.fd, self.inotify.ready)
        loop.add_reader(self.socket.fileno(), self.datagrams)
        for home in tuple(self.homes):
            self.watch_home(home)
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop.set)
        notifications = asyncio.create_task(self.notifications.run())
        self.wake()
        try:
            while not self.stop.is_set():
                pending = [t.recovery for t in self.targets.values() if t.recovery.error and not t.recovery.halted and t.recovery.phase != 'verifying']
                deadlines = [r.deadline if r.phase != 'watching' else r.due if r.due > time.time() else r.due + 300 for r in pending]
                timeout = max(0.1, min(deadlines) - time.time()) if deadlines else None
                changed = asyncio.create_task(self.changed.wait())
                stopped = asyncio.create_task(self.stop.wait())
                _, waiting = await asyncio.wait((changed, stopped), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                for task in waiting:
                    task.cancel()
                await asyncio.gather(*waiting, return_exceptions=True)
                if self.stop.is_set():
                    break
                await asyncio.sleep(0.35)
                self.changed.clear()
                try:
                    if self.scan:
                        self.scan = False
                        await reconcile(self)
                    await evaluate(self)
                except (OSError, ValueError) as error:
                    logger.error('監視処理エラー %s', type(error).__name__)
        finally:
            self.event_path.unlink(missing_ok=True)
            for server in self.servers.values():
                await server.close()
            for key in list(self.targets):
                self.remove(key)
            notifications.cancel()
            await asyncio.gather(notifications, return_exceptions=True)
            loop.remove_reader(self.inotify.fd)
            loop.remove_reader(self.socket.fileno())
            os.close(self.inotify.fd)
            self.socket.close()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('DISCORD_WEBHOOK_URL'):
        raise SystemExit('環境変数DISCORD_WEBHOOK_URLを設定してください')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.config.stat().st_mode & 0o077:
        raise SystemExit('設定ファイルの権限を600にしてください')
    with args.config.open('rb') as source:
        config = tomllib.load(source)
    asyncio.run(Monitor(config).run())


if __name__ == '__main__':
    main()
