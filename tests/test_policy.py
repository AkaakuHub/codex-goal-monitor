import unittest

from monitor.adapter import (
    empty_composer,
    event,
    idle_stalled,
    resume_selected,
    status_thread,
    terminal_capacity,
)
from monitor.policy import Recovery, capacity_for_goal


class RecoveryTests(unittest.TestCase):
    def test_status_identifies_the_current_thread_without_guessing(self):
        thread = '01a132dd-56bc-78d3-84da-06fe6a123456'
        self.assertEqual(status_thread('│ Session: ' + thread + ' │'), thread)
        self.assertEqual(status_thread('│ Session: ' + thread[:20] + '\n│ ' + thread[20:] + ' │'), thread)
        self.assertIsNone(status_thread('Session: unknown'))
        self.assertIsNone(status_thread('a prompt mentioned Session: ' + thread))

    def test_capacity_must_belong_to_an_existing_goal(self):
        self.assertFalse(capacity_for_goal(10, 20, None))
        self.assertFalse(capacity_for_goal(10, 20, 15000))
        self.assertTrue(capacity_for_goal(16, 20, 15000))
        self.assertFalse(capacity_for_goal(16, 2000, 15000))
        self.assertFalse(capacity_for_goal(25, 20, 15000))

    def test_only_capacity_blocked_can_resume(self):
        recovery = Recovery()
        self.assertFalse(recovery.eligible('blocked', 'goal', 50))
        self.assertTrue(recovery.capacity('error-one', 10, [30, 60, 120]))
        self.assertFalse(recovery.eligible('blocked', 'goal', 39))
        self.assertTrue(recovery.eligible('blocked', 'goal', 40))
        for status in ('active', 'paused', 'usage_limited', 'budget_limited', 'complete'):
            self.assertFalse(recovery.eligible(status, 'goal', 40))

    def test_deduplication_and_backoff(self):
        recovery = Recovery()
        recovery.capacity('first', 0, [30, 60, 120, 300, 600])
        self.assertFalse(recovery.capacity('first', 10, [30, 60, 120, 300, 600]))
        recovery.cancel()
        recovery.capacity('second', 10, [30, 60, 120, 300, 600])
        self.assertEqual(recovery.due, 70)
        recovery.success()
        self.assertFalse(recovery.capacity('second', 100, [30]))
        self.assertTrue(recovery.capacity('third', 100, [30, 60]))
        self.assertEqual(recovery.due, 130)

    def test_success_resets_retry_counts_and_no_progress_count(self):
        recovery = Recovery(resumes=5, attempt=4, wasted_turns=3)
        recovery.success()
        self.assertEqual((recovery.resumes, recovery.attempt, recovery.wasted_turns), (0, 0, 0))

    def test_capacity_without_token_consumption_does_not_exhaust_recovery(self):
        recovery = Recovery(token_baseline=100)
        for count in range(12):
            recovery.resumes += 1
            recovery.failed_turn(100, False)
            recovery.cancel()
            self.assertTrue(recovery.capacity(str(count), count * 700, [30, 60, 120, 300, 600]))
        self.assertEqual(recovery.wasted_turns, 0)
        self.assertEqual(recovery.due, 11 * 700 + 600)

    def test_repeated_token_consumption_without_new_results_is_counted(self):
        recovery = Recovery(resumes=1, token_baseline=100)
        for tokens in range(101, 106):
            recovery.failed_turn(tokens, False)
        self.assertEqual(recovery.wasted_turns, 5)
        recovery.failed_turn(110, True)
        self.assertEqual(recovery.wasted_turns, 0)

    def test_different_goal_and_stale_error_are_rejected(self):
        recovery = Recovery(goal_id='first')
        recovery.capacity('error', 0, [30])
        self.assertFalse(recovery.eligible('blocked', 'second', 50))
        self.assertFalse(recovery.eligible('blocked', 'first', 1801))
        recovery.halted = True
        self.assertFalse(recovery.eligible('blocked', 'first', 50))

    def test_typing_busy_and_menus_are_protected(self):
        screen = '■ Selected model is at capacity. Please try a different model.\n\n› Ask Codex to do anything\n\nGoal stalled (/goal resume)'
        self.assertTrue(idle_stalled(screen, 2, 2))
        self.assertTrue(terminal_capacity(screen, 2))
        self.assertFalse(idle_stalled(screen, 3, 2))
        self.assertFalse(idle_stalled(screen.replace('Ask Codex to do anything', 'user draft'), 2, 2))
        self.assertFalse(idle_stalled(screen.replace('■', 'Working (esc to interrupt)\n■'), 2, 3))
        self.assertFalse(empty_composer('› Ask Codex to do anything else', 2, 0))
        self.assertFalse(resume_selected('Resume paused goal?\n› Leave paused\nResume goal'))
        self.assertTrue(resume_selected('Resume paused goal?\n› 1. Resume goal\n2. Leave paused'))

    def test_capacity_is_a_terminal_error_not_old_transcript(self):
        screen = '■ Selected model is at capacity. Please try a different model.\nUser requested approval\n›\nGoal stalled (/goal resume)'
        self.assertFalse(terminal_capacity(screen, 2))
        self.assertFalse(terminal_capacity('Selected model is at capacity. Please try a different model.\n›', 1))

    def test_actual_error_protocol_and_turn_boundaries(self):
        line = b'{"type":"event_msg","payload":{"type":"task_complete","turn_id":"a","error":{"codex_error_info":"server_overloaded"}}}'
        self.assertEqual(event(line), ('capacity', 'a'))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"task_started","turn_id":"b"}}'), ('started', 'b'))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"task_complete","turn_id":"b"}}'), ('ended', 'b'))
        self.assertEqual(event(b'{"type":"response_item","payload":{"type":"message"}}'), ('', None))
        self.assertEqual(event(b'partial'), ('', None))


if __name__ == '__main__':
    unittest.main()
