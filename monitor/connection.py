import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from websockets.client import ClientProtocol
from websockets.frames import OP_CONT, OP_TEXT, Frame
from websockets.http11 import Response
from websockets.uri import parse_uri

from .configuration import Settings

Reply = Callable[[dict[str, object] | None], None]


class Connection(QObject):
    ready = Signal()
    notification = Signal(str, dict)
    disconnected = Signal()
    problem = Signal(str)

    def __init__(self, settings: Settings, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.process = QProcess(self)
        self.process.started.connect(self.handshake)
        self.process.readyReadStandardOutput.connect(self.receive)
        self.process.readyReadStandardError.connect(self.process.readAllStandardError)
        self.process.finished.connect(self.closed)
        self.process.errorOccurred.connect(self.process_error)
        self.pending: dict[int, tuple[Reply, QTimer]] = {}
        self.sequence = 0
        self.protocol = ClientProtocol(parse_uri('ws://localhost/'), max_size=2**20)
        self.fragment = bytearray()
        self.handshake_timer = QTimer(self, singleShot=True, interval=10000)
        self.handshake_timer.timeout.connect(self.abort)

    def start(self) -> None:
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('CODEX_HOME', self.settings.codex_home)
        self.process.setProcessEnvironment(environment)
        command = shutil.which(self.settings.codex_command) or self.settings.codex_command
        path = Path(self.settings.codex_home) / 'app-server-control/app-server-control.sock'
        arguments = ['app-server', 'proxy', '--sock', str(path)]
        if os.name == 'nt' and Path(command).suffix.lower() in ('.cmd', '.bat'):
            self.process.setNativeArguments(f'/d /s /c ""{command}" app-server proxy --sock "{path}""')
            self.process.start(os.environ['COMSPEC'], [])
        else:
            self.process.start(command, arguments)
        self.handshake_timer.start()

    def handshake(self) -> None:
        self.protocol.send_request(self.protocol.connect())
        self.flush()

    def flush(self) -> None:
        for data in self.protocol.data_to_send():
            if data:
                self.process.write(data)

    def receive(self) -> None:
        self.protocol.receive_data(bytes(self.process.readAllStandardOutput()))
        for event in self.protocol.events_received():
            if isinstance(event, Response):
                if self.protocol.handshake_exc:
                    self.abort()
                    return
                self.request('initialize', {
                    'clientInfo': {'name': 'codex-goal-monitor', 'version': '0.2.0'},
                    'capabilities': {'experimentalApi': True},
                }, self.initialized)
            elif isinstance(event, Frame) and event.opcode in (OP_TEXT, OP_CONT):
                self.fragment.extend(event.data)
                if event.fin:
                    try:
                        message = json.loads(self.fragment)
                        if not isinstance(message, dict):
                            raise ValueError('Invalid message')
                        self.dispatch(message)
                    except (ValueError, TypeError):
                        self.abort()
                        return
                    self.fragment.clear()
        self.flush()

    def initialized(self, result: dict[str, object] | None) -> None:
        if result is None:
            self.abort()
            return
        self.handshake_timer.stop()
        self.send({'method': 'initialized'})
        self.ready.emit()

    def send(self, message: dict[str, object]) -> None:
        self.protocol.send_text(json.dumps(message).encode())
        self.flush()

    def request(self, method: str, params: dict[str, object], reply: Reply) -> None:
        self.sequence += 1
        identifier = self.sequence
        timer = QTimer(self, singleShot=True, interval=10000)
        timer.timeout.connect(lambda: self.timeout(identifier))
        self.pending[identifier] = reply, timer
        self.send({'id': identifier, 'method': method, 'params': params})
        timer.start()

    def timeout(self, identifier: int) -> None:
        reply, timer = self.pending.pop(identifier)
        timer.deleteLater()
        reply(None)
        self.problem.emit('Codexからの応答がありません。設定から再接続してください。')

    def dispatch(self, message: dict[str, object]) -> None:
        identifier = message.get('id')
        if isinstance(identifier, int) and identifier in self.pending:
            reply, timer = self.pending.pop(identifier)
            timer.stop()
            timer.deleteLater()
            result = message.get('result')
            if not isinstance(result, dict):
                self.problem.emit('Codexの操作に失敗しました。CLIのバージョンと接続先を確認してください。')
            reply(result if isinstance(result, dict) else None)
        elif isinstance(message.get('method'), str) and 'id' not in message:
            params = message.get('params')
            if isinstance(params, dict):
                self.notification.emit(message['method'], params)

    def process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.handshake_timer.stop()
            self.problem.emit('Codex CLIを起動できません。設定の実行ファイルを確認してください。')
            self.disconnected.emit()

    def abort(self) -> None:
        self.problem.emit('Codexに接続できません。CLIのバージョンと接続先を確認してください。')
        self.process.kill()

    def closed(self) -> None:
        self.handshake_timer.stop()
        for _, timer in self.pending.values():
            timer.stop()
            timer.deleteLater()
        self.pending.clear()
        self.disconnected.emit()

    def stop(self) -> None:
        self.handshake_timer.stop()
        self.process.closeWriteChannel()
        if not self.process.waitForFinished(1000):
            self.process.kill()
            self.process.waitForFinished(1000)
