import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .connection import Connection
from .domain.recovery import Goal, Recovery


@dataclass
class Target:
    goal: Goal
    recovery: Recovery
    timer: QTimer
    changed: QTimer
    turn: str = ''


class Observer(QObject):
    notify = Signal(str, str, str)

    def __init__(self, connection: Connection):
        super().__init__(connection)
        self.connection = connection
        self.targets: dict[str, Target] = {}
        connection.ready.connect(lambda: self.loaded({}))
        connection.notification.connect(self.received_event)
        connection.disconnected.connect(self.clear)

    def loaded(self, params: dict[str, object]) -> None:
        def received(result: dict[str, object] | None) -> None:
            if result is None:
                return
            for thread in result.get('data', []):
                if isinstance(thread, str):
                    self.snapshot(thread)
            if result.get('nextCursor'):
                self.loaded({'cursor': result['nextCursor']})
        self.connection.request('thread/loaded/list', params, received)

    def snapshot(self, thread: str) -> None:
        self.connection.request('thread/goal/get', {'threadId': thread}, lambda result: self.goal(thread, result.get('goal') if result else None, initial=True))

    def received_event(self, method: str, params: dict[str, object]) -> None:
        thread = params.get('threadId')
        if method == 'thread/started':
            data = params.get('thread')
            if isinstance(data, dict) and isinstance(data.get('id'), str) and data['id'] not in self.targets:
                self.snapshot(data['id'])
        elif isinstance(thread, str):
            if method == 'thread/goal/updated':
                turn = params.get('turnId')
                self.goal(thread, params.get('goal'), turn if isinstance(turn, str) else '')
            elif method in ('thread/goal/cleared', 'thread/closed'):
                self.remove(thread)
            elif method == 'thread/status/changed' and thread in self.targets:
                status = params.get('status')
                if isinstance(status, dict):
                    if status.get('type') == 'notLoaded':
                        self.remove(thread)
                    elif status.get('type') in ('idle', 'systemError') and self.targets[thread].recovery.phase in ('sent', 'verifying'):
                        self.targets[thread].changed.start()

    def goal(self, thread: str, value: object, turn: str = '', initial: bool = False) -> None:
        if not isinstance(value, dict):
            return
        try:
            goal = Goal.parse(value)
        except ValueError:
            return
        target = self.targets.get(thread)
        if target and initial:
            return
        if target and target.goal.identity != goal.identity:
            self.remove(thread)
            target = None
        previous = target.goal.status if target else ''
        if target is None:
            timer = QTimer(self, singleShot=True)
            changed = QTimer(self, singleShot=True, interval=500)
            timer.timeout.connect(lambda: self.deadline(thread))
            changed.timeout.connect(lambda: self.inspect(thread))
            target = Target(goal, Recovery(), timer, changed)
            self.targets[thread] = target
        target.goal = goal
        if turn:
            target.turn = turn
        recovery = target.recovery
        if goal.status in ('complete', 'usageLimited', 'paused', 'budgetLimited'):
            target.timer.stop()
            target.changed.stop()
            recovery.cancel()
            if not initial and goal.status != previous and goal.status in ('complete', 'usageLimited'):
                self.notify.emit(thread, 'Codex Goal Completed' if goal.status == 'complete' else 'Codex Goal Usage Limited', goal.status)
        elif goal.status == 'blocked' and (previous != 'blocked' or turn != recovery.last_turn):
            target.changed.start()
        elif goal.status == 'active':
            if recovery.phase == 'sent':
                recovery.phase = 'verifying'
                self.notify.emit(thread, 'Codex Goal Resume Started', '最初のターンの完了を確認しています。')
            elif recovery.phase == 'waiting':
                recovery.cancel()
                target.timer.stop()
            if recovery.phase == 'verifying' and turn:
                target.changed.start()

    def inspect(self, thread: str) -> None:
        target = self.targets.get(thread)
        if target is None:
            return
        def received(result: dict[str, object] | None) -> None:
            if result is None or self.targets.get(thread) is not target:
                return
            turns = result.get('data')
            if not isinstance(turns, list):
                return
            recovery = target.recovery
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                if target.goal.status == 'blocked' and (not target.turn or turn.get('id') == target.turn):
                    before = recovery.phase
                    if recovery.schedule(turn, target.goal, time.time()):
                        target.timer.start(max(1, round((recovery.due - time.time()) * 1000)))
                        self.notify.emit(thread, 'Codex Goal Recovery Scheduled', 'Capacityエラーまたは通信切断からの再開を待機します。')
                    elif before != 'halted' and recovery.phase == 'halted':
                        target.timer.stop()
                        self.notify.emit(thread, 'Codex Goal Recovery Stopped', 'トークンを消費する復旧失敗が5回続いたため停止しました。')
                    elif recovery.phase in ('sent', 'verifying'):
                        recovery.cancel()
                        target.timer.stop()
                        self.notify.emit(thread, 'Codex Goal Recovery Failed', '再開後のターンが正常終了しませんでした。')
                    break
                if turn.get('id') == recovery.last_turn:
                    break
                if recovery.complete(turn):
                    target.timer.stop()
                    self.notify.emit(thread, 'Codex Goal Resumed', '再開後の最初のターンが正常終了しました。')
                    break
        self.connection.request('thread/turns/list', {'threadId': thread, 'limit': 2, 'itemsView': 'notLoaded'}, received)

    def deadline(self, thread: str) -> None:
        target = self.targets.get(thread)
        if target is None:
            return
        recovery = target.recovery
        if recovery.phase in ('sent', 'verifying'):
            recovery.phase = 'halted'
            self.notify.emit(thread, 'Codex Goal Recovery Stopped', '再開結果を確認できなかったため停止しました。')
        elif recovery.eligible(target.goal, time.time()):
            self.connection.request('thread/read', {'threadId': thread}, lambda result: self.resume(thread, target, result))

    def resume(self, thread: str, target: Target, result: dict[str, object] | None) -> None:
        if self.targets.get(thread) is not target or result is None:
            return
        metadata = result.get('thread')
        if not isinstance(metadata, dict):
            return
        status = metadata.get('status')
        if not isinstance(status, dict) or status.get('type') not in ('idle', 'systemError'):
            return
        def checked(result: dict[str, object] | None) -> None:
            if self.targets.get(thread) is not target or result is None or not isinstance(result.get('goal'), dict):
                return
            try:
                current = Goal.parse(result['goal'])
            except ValueError:
                return
            recovery = target.recovery
            if current.identity != target.goal.identity or not recovery.eligible(current, time.time()):
                return
            recovery.phase = 'sent'
            target.timer.start(45000)
            self.connection.request('thread/goal/set', {'threadId': thread, 'status': 'active', 'origin': 'automatic'}, updated)
        def updated(result: dict[str, object] | None) -> None:
            if self.targets.get(thread) is not target:
                return
            if result is None:
                target.timer.stop()
                target.recovery.phase = 'halted'
                self.notify.emit(thread, 'Codex Goal Recovery Stopped', '再開要求の結果が不明なため、追加の操作を停止しました。')
            else:
                self.goal(thread, result.get('goal'))
        self.connection.request('thread/goal/get', {'threadId': thread}, checked)

    def remove(self, thread: str) -> None:
        target = self.targets.pop(thread, None)
        if target:
            for timer in (target.timer, target.changed):
                timer.stop()
                timer.deleteLater()

    def clear(self) -> None:
        for thread in tuple(self.targets):
            self.remove(thread)
