import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, QTimer

from ..configuration import config_path, load
from ..runtime import Runtime


def main() -> None:
    parser = argparse.ArgumentParser(description='Codex Goalの監視・復旧とDiscord通知')
    parser.add_argument('--headless', action='store_true', help='トレイを表示せず監視します（Linuxサーバー・WSL用）')
    parser.add_argument('--config', type=Path, default=config_path(), help='設定JSONのパス')
    args = parser.parse_args()
    if args.headless:
        app = QCoreApplication(sys.argv[:1])
    else:
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv[:1])
        app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('Codex Goal Monitor')
    args.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = QLockFile(str(args.config.with_suffix('.lock')))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        parser.exit(message='同じ設定のCodex Goal Monitorがすでに起動しています。\n')
    try:
        settings = load(args.config)
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f'設定を読み込めません（{type(error).__name__}）。\n')
    if args.headless:
        try:
            settings.validate()
        except ValueError as error:
            parser.exit(1, str(error) + '\n')
        runtime = Runtime(settings, app)
        runtime.status.connect(lambda text: print(text, flush=True))
        app.aboutToQuit.connect(runtime.stop)
        QTimer.singleShot(0, runtime.refresh)
    else:
        from .tray import Tray
        tray = Tray(settings, args.config, app)
        app.aboutToQuit.connect(tray.stop)
        QTimer.singleShot(0, tray.start)
    try:
        sys.exit(app.exec())
    finally:
        lock.unlock()
