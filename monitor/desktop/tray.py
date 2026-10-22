import sys
from pathlib import Path

import qtawesome
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from ..configuration import Settings, save
from ..runtime import Runtime
from .settings import SettingsDialog


class Tray(QObject):
    def __init__(self, settings: Settings, path: Path, app: QApplication):
        super().__init__(app)
        self.settings = settings
        self.path = path
        self.runtime: Runtime | None = None
        icon = qtawesome.icon('fa6s.bullseye', color='#000000' if sys.platform == 'darwin' else '#3b82f6')
        icon.setIsMask(sys.platform == 'darwin')
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('Codex Goal Monitor')
        self.menu = QMenu()
        self.status = self.menu.addAction('未設定です。')
        self.status.setEnabled(False)
        self.menu.addAction('設定…', self.configure)
        self.menu.addSeparator()
        self.menu.addAction('終了', app.quit)
        self.tray.setContextMenu(self.menu)

    def start(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.critical(None, 'トレイを利用できません', 'システムトレイが必要です。LinuxサーバーやWSLでは--headlessで起動してください。')
            QApplication.quit()
            return
        self.tray.show()
        try:
            self.settings.validate()
        except ValueError:
            self.configure()
        else:
            self.monitor()

    def configure(self) -> None:
        dialog = SettingsDialog(self.settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            save(self.path, dialog.value)
        except OSError:
            QMessageBox.warning(None, '保存できません', '設定ファイルの保存先とアクセス権限を確認してください。')
            return
        self.settings = dialog.value
        self.monitor()

    def monitor(self) -> None:
        if self.runtime is not None:
            self.runtime.stop()
            self.runtime.deleteLater()
        self.runtime = Runtime(self.settings, self)
        self.runtime.status.connect(self.status.setText)
        self.runtime.refresh()

    def stop(self) -> None:
        if self.runtime is not None:
            self.runtime.stop()
        self.tray.hide()
