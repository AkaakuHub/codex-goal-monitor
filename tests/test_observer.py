import time
import unittest
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication

from monitor.configuration import Settings
from monitor.connection import Connection
from monitor.observer import Observer


class ObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.connection = Connection(Settings())
        self.connection.request = Mock()
        self.observer = Observer(self.connection)
        self.notifications = Mock()
        self.observer.notify.connect(self.notifications)
        self.goal = {'status': 'blocked', 'createdAt': int(time.time()) - 10, 'objective': 'Test', 'tokensUsed': 100}

    def tearDown(self):
        self.observer.clear()
        self.connection.deleteLater()

    def reply(self, result):
        self.connection.request.call_args.args[2](result)

    def schedule(self):
        self.observer.goal('thread', self.goal, 'failed')
        self.observer.inspect('thread')
        self.reply({'data': [{'id': 'failed', 'status': 'failed', 'startedAt': int(time.time()), 'error': {'message': '', 'codexErrorInfo': 'serverOverloaded'}}]})
        target = self.observer.targets['thread']
        target.recovery.due = time.time() - 1
        return target

    def test_only_loaded_idle_blocked_goal_receives_resume(self):
        target = self.schedule()
        self.observer.deadline('thread')
        self.assertEqual(self.connection.request.call_args.args[0], 'thread/read')
        self.reply({'thread': {'status': {'type': 'systemError'}}})
        self.assertEqual(self.connection.request.call_args.args[0], 'thread/goal/get')
        self.reply({'goal': self.goal})
        self.assertEqual(self.connection.request.call_args.args[:2], ('thread/goal/set', {'threadId': 'thread', 'status': 'active', 'origin': 'automatic'}))
        self.reply({'goal': {**self.goal, 'status': 'active'}})
        self.assertEqual(target.recovery.phase, 'verifying')
        self.assertNotIn('Codex Goal Resumed', [call.args[1] for call in self.notifications.call_args_list])
        self.observer.inspect('thread')
        self.reply({'data': [{'id': 'next-running', 'status': 'inProgress'}, {'id': 'resumed', 'status': 'completed'}]})
        self.assertEqual(self.notifications.call_args.args[1], 'Codex Goal Resumed')

    def test_no_resume_if_user_pauses_during_recheck(self):
        self.schedule()
        self.observer.deadline('thread')
        self.reply({'thread': {'status': {'type': 'idle'}}})
        self.observer.goal('thread', {**self.goal, 'status': 'paused'})
        self.reply({'goal': {**self.goal, 'status': 'paused'}})
        self.assertNotIn('thread/goal/set', [call.args[0] for call in self.connection.request.call_args_list])

    def test_closed_or_active_thread_is_never_loaded_or_resumed(self):
        for status in ('notLoaded', 'active'):
            with self.subTest(status=status):
                self.observer.clear()
                self.connection.request.reset_mock()
                self.schedule()
                self.observer.deadline('thread')
                count = self.connection.request.call_count
                self.reply({'thread': {'status': {'type': status}}})
                self.assertEqual(self.connection.request.call_count, count)

    def test_replaced_goal_invalidates_pending_recheck(self):
        self.schedule()
        self.observer.deadline('thread')
        callback = self.connection.request.call_args.args[2]
        self.observer.goal('thread', {**self.goal, 'objective': 'New goal', 'status': 'paused'})
        count = self.connection.request.call_count
        callback({'thread': {'status': {'type': 'idle'}}})
        self.assertEqual(self.connection.request.call_count, count)

    def test_initial_completed_goal_is_not_notified_but_new_completion_is(self):
        self.observer.goal('thread', {**self.goal, 'status': 'complete'}, initial=True)
        self.notifications.assert_not_called()
        self.observer.goal('thread', {**self.goal, 'status': 'active'})
        self.observer.goal('thread', {**self.goal, 'status': 'complete'})
        self.observer.goal('thread', {**self.goal, 'status': 'complete'})
        self.assertEqual(self.notifications.call_count, 1)


if __name__ == '__main__':
    unittest.main()
