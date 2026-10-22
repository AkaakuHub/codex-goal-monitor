import unittest

from monitor.domain.recovery import Goal, Recovery, retryable


def failed(identifier: str = 'failed', info: object = 'serverOverloaded', started: int = 100) -> dict[str, object]:
    return {'id': identifier, 'status': 'failed', 'startedAt': started, 'error': {'message': '', 'codexErrorInfo': info}}


class RecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.goal = Goal('blocked', 90, 'Finish the task', 100)

    def test_only_capacity_and_stream_failures_are_retryable(self):
        for info in ('serverOverloaded', 'rateLimitExceeded', {'httpConnectionFailed': {'httpStatusCode': 429}}, {'responseStreamDisconnected': {'httpStatusCode': 500}}):
            self.assertTrue(retryable(failed(info=info), self.goal, 110))
        for info in ('usageLimitExceeded', 'contextWindowExceeded', 'unauthorized', 'other'):
            self.assertFalse(retryable(failed(info=info), self.goal, 110))
        for status in ('inProgress', 'interrupted', 'completed'):
            self.assertFalse(retryable({**failed(), 'status': status}, self.goal, 110))

    def test_remote_compaction_stream_error_is_retryable(self):
        turn = {**failed(info='other'), 'error': {'message': 'Error running remote compact task: stream disconnected before completion: connection reset'}}
        self.assertTrue(retryable(turn, self.goal, 110))

    def test_error_must_belong_to_the_current_goal_and_be_recent(self):
        self.assertFalse(retryable(failed(started=89), self.goal, 110))
        self.assertFalse(retryable(failed(started=111), self.goal, 110))
        self.assertFalse(retryable(failed(), self.goal, 1901))

    def test_backoff_deduplicates_the_same_failed_turn(self):
        recovery = Recovery()
        for index, delay in enumerate((30, 60, 120, 300, 600, 600)):
            self.assertTrue(recovery.schedule(failed(str(index)), self.goal, 110))
            self.assertEqual(recovery.due, 110 + delay)
            self.assertFalse(recovery.schedule(failed(str(index)), self.goal, 110))
            self.assertEqual(recovery.attempt, index + 1)

    def test_paused_complete_and_limited_goals_are_never_resumed(self):
        recovery = Recovery()
        recovery.schedule(failed(), self.goal, 110)
        self.assertTrue(recovery.eligible(self.goal, 140))
        self.assertFalse(recovery.eligible(self.goal, 139))
        for status in ('paused', 'complete', 'usageLimited', 'budgetLimited', 'active'):
            goal = Goal(status, 90, self.goal.objective, 100)
            self.assertFalse(recovery.eligible(goal, 140))
            self.assertFalse(Recovery().schedule(failed(), goal, 110))
        self.assertFalse(recovery.eligible(self.goal, 1911))

    def test_capacity_without_token_consumption_keeps_retrying(self):
        recovery = Recovery()
        for index in range(20):
            self.assertTrue(recovery.schedule(failed(str(index)), self.goal, 110))
        self.assertEqual(recovery.wasted, 0)

    def test_five_token_consuming_failed_resumes_stop(self):
        recovery = Recovery()
        self.assertTrue(recovery.schedule(failed('initial'), self.goal, 110))
        for index in range(1, 6):
            goal = Goal('blocked', 90, self.goal.objective, 100 + index)
            scheduled = recovery.schedule(failed(str(index)), goal, 110)
            self.assertEqual(scheduled, index < 5)
        self.assertEqual(recovery.phase, 'halted')
        self.assertFalse(recovery.eligible(goal, 1000))

    def test_only_a_new_successful_turn_confirms_recovery(self):
        recovery = Recovery(attempt=2, last_turn='failed', phase='verifying', wasted=3)
        for turn in ({'id': 'new', 'status': 'inProgress'}, {'id': 'new', 'status': 'interrupted'}, failed('new'), {'id': 'failed', 'status': 'completed'}):
            self.assertFalse(recovery.complete(turn))
        self.assertTrue(recovery.complete({'id': 'new', 'status': 'completed'}))
        self.assertEqual((recovery.attempt, recovery.wasted, recovery.phase), (0, 0, 'watching'))


if __name__ == '__main__':
    unittest.main()
