from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Signal

from .configuration import Settings
from .connection import Connection
from .desktop.notifications import Notifications
from .observer import Observer


class Runtime(QObject):
    status = Signal(str)

    def __init__(self, settings: Settings, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.path = Path(settings.codex_home) / 'app-server-control/app-server-control.sock'
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.refresh)
        self.connection: Connection | None = None
        self.observer: Observer | None = None
        self.identity: tuple[int, int, int] | None = None
        self.error = ''
        self.notifications = Notifications(settings, self)
        self.notifications.problem.connect(self.status)

    def refresh(self) -> None:
        directories: set[str] = set()
        for path in (self.path, self.path.resolve()):
            parent = path.parent
            while not parent.is_dir() and parent != parent.parent:
                parent = parent.parent
            directories.add(str(parent))
        previous = set(self.watcher.directories())
        if previous - directories:
            self.watcher.removePaths(sorted(previous - directories))
        if directories - previous:
            self.watcher.addPaths(sorted(directories - previous))
        try:
            info = self.path.stat()
            identity = info.st_dev, info.st_ino, info.st_mtime_ns
        except OSError:
            identity = None
        if self.identity == identity:
            if self.connection is None:
                self.status.emit('Codexの起動を待っています。')
            return
        self.identity = identity
        if self.connection is not None:
            self.connection.blockSignals(True)
            if self.observer is not None:
                self.observer.clear()
            self.connection.stop()
            self.connection.deleteLater()
            self.connection = None
        if identity is None:
            self.status.emit('Codexの起動を待っています。')
            return
        self.error = ''
        self.connection = Connection(self.settings, self)
        self.observer = Observer(self.connection)
        self.observer.notify.connect(self.notifications.send)
        self.connection.problem.connect(self.problem)
        self.connection.ready.connect(lambda: self.status.emit('監視中です。'))
        self.connection.disconnected.connect(lambda: self.status.emit(self.error or 'Codexの起動を待っています。'))
        self.status.emit('Codexに接続しています。')
        self.connection.start()

    def problem(self, message: str) -> None:
        self.error = message
        self.status.emit(message)

    def stop(self) -> None:
        self.blockSignals(True)
        self.watcher.blockSignals(True)
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if self.observer is not None:
            self.observer.clear()
        if self.connection is not None:
            self.connection.stop()
        self.notifications.stop()
