import asyncio
import logging
import os
import stat
from typing import TYPE_CHECKING

from . import tmux
from .identity import stable_title
from .processes import descendant, discover
from .tracking import Target, binding

if TYPE_CHECKING:
    from .service import Monitor


logger = logging.getLogger(__name__)


async def reconcile(monitor: "Monitor") -> None:
    sockets = set(monitor.explicit)
    for directory in monitor.directories:
        monitor.inotify.add(directory.parent)
        monitor.inotify.add(directory)
        if directory.is_dir():
            for item in directory.iterdir():
                try:
                    info = item.stat()
                    if stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
                        sockets.add(item)
                except OSError:
                    pass
    for item in monitor.explicit:
        monitor.inotify.add(item.parent)
    results = await asyncio.gather(*(tmux.panes(s) for s in sockets))
    all_panes = [pane for group in results for pane in group]
    live_sockets = {p.socket for p in all_panes}
    for server_socket in list(monitor.servers):
        server = monitor.servers[server_socket]
        if server_socket not in live_sockets or server.process and server.process.returncode is not None:
            await server.close()
            del monitor.servers[server_socket]
    for server_socket in live_sockets - monitor.servers.keys():
        server = tmux.Server(server_socket, monitor.helper, monitor.event_path, monitor.wake, lambda pane, server_socket=server_socket: monitor.output(server_socket, pane))
        await server.start(next(p.session for p in all_panes if p.socket == server_socket))
        monitor.servers[server_socket] = server
    processes = await asyncio.to_thread(discover)
    found: set[str] = set()
    for pane in all_panes:
        candidates = [p for p in processes if p.tty == pane.tty and descendant(p.pid, pane.pid)]
        if len(candidates) != 1:
            continue
        process = candidates[0]
        found.add(pane.key)
        target = monitor.targets.get(pane.key)
        if target and target.process != process:
            monitor.remove(pane.key)
            target = None
        if not target:
            try:
                pidfd = os.pidfd_open(process.pid)
            except OSError:
                continue
            target = Target(pane, process, pidfd)
            monitor.targets[pane.key] = target
            asyncio.get_running_loop().add_reader(pidfd, monitor.wake)
            monitor.watch_home(process.home)
            logger.info('Codexを検出 pane=%s pid=%s', pane.label, process.pid)
        target.pane = pane
        identity = binding(process, pane)
        if identity:
            thread, path = identity
            target.bind(thread, path, monitor.state.get(f'{process.home}:{thread}'))
        elif target.thread and (not target.proof_at or stable_title(pane.title) != target.proof_title):
            target.thread = None
            target.rollout = None
        await monitor.servers[pane.socket].subscribe(pane.pane)
    for key in monitor.targets.keys() - found:
        monitor.remove(key)

