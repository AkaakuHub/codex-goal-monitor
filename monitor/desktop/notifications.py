import json
from collections import deque

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..configuration import Settings


class Notifications(QObject):
    problem = Signal(str)

    def __init__(self, settings: Settings, parent: QObject):
        super().__init__(parent)
        self.settings = settings
        self.manager = QNetworkAccessManager(self)
        self.queue: deque[str] = deque()
        self.attempt = 0
        self.reply: QNetworkReply | None = None
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.post)

    def send(self, thread: str, title: str, detail: str) -> None:
        if len(self.queue) >= 100:
            self.problem.emit('Discord通知の待機件数が上限に達しました。')
            return
        self.queue.append(f'{title}\nSource: {self.settings.sender_label}\nThread: {thread}\n{detail}'[:1900])
        if self.reply is None and not self.timer.isActive():
            self.post()

    def post(self) -> None:
        if not self.queue:
            return
        request = QNetworkRequest(QUrl(self.settings.webhook_url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        request.setTransferTimeout(10000)
        payload = {'content': self.queue[0], 'username': self.settings.sender_label, 'allowed_mentions': {'parse': []}}
        self.reply = self.manager.post(request, json.dumps(payload).encode())
        self.reply.finished.connect(self.finished)

    def finished(self) -> None:
        reply = self.reply
        if reply is None:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        data = bytes(reply.readAll())
        success = reply.error() == QNetworkReply.NetworkError.NoError
        reply.deleteLater()
        self.reply = None
        self.attempt += 1
        if success or self.attempt >= 5 or isinstance(status, int) and 400 <= status < 500 and status != 429:
            self.queue.popleft()
            self.attempt = 0
            if not success:
                self.problem.emit('Discord通知に失敗しました。Webhook URLと接続を確認してください。')
            self.post()
            return
        delay = 5.0
        if status == 429:
            try:
                delay = min(60.0, max(1.0, float(json.loads(data).get('retry_after', 5))))
            except (ValueError, TypeError, AttributeError):
                pass
        self.timer.start(round(delay * 1000))

    def stop(self) -> None:
        self.timer.stop()
        if self.reply is not None:
            self.reply.finished.disconnect(self.finished)
            self.reply.abort()
            self.reply.deleteLater()
            self.reply = None
        self.queue.clear()
