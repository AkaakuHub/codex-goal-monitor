import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from monitor.adapter import Goal, event
from monitor.policy import Recovery
from monitor.recovery import recover
from monitor.tracking import Target


class ResumedTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_alone_is_started_not_success(self):
        target = Mock()
        target.recovery = Recovery(phase='sent', started=True, busy=True)
        target.thread = 'thread'
        notify = Mock()
        with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'active', 0, 0, 0)):
            await recover(target, 'Pursuing goal', notify, Mock(), 3)
        self.assertEqual(target.recovery.phase, 'verifying')
        self.assertEqual(notify.call_args.args[1], 'Codex Goal Resume Started')

    async def test_success_requires_a_completed_resumed_turn(self):
        target = Mock()
        target.recovery = Recovery(phase='verifying')
        notify = Mock()
        with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'active', 0, 0, 0)):
            await recover(target, 'Pursuing goal', notify, Mock(), 3)
            notify.assert_not_called()
            target.recovery.progressed = True
            await recover(target, 'Pursuing goal', notify, Mock(), 3)
        self.assertEqual(notify.call_args.args[1], 'Codex Goal Resumed')
        self.assertEqual(target.recovery.phase, 'watching')

    def test_failed_and_aborted_turns_are_not_successful(self):
        stream = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn', 'error': {'codex_error_info': 'other', 'message': 'stream disconnected before completion: An error occurred while processing your request.'}}}
        self.assertEqual(event(json.dumps(stream).encode()), ('stream', 'turn'))
        stream['payload']['error']['message'] = 'Permission denied'
        self.assertEqual(event(json.dumps(stream).encode()), ('failed', 'turn'))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"turn_aborted","turn_id":"turn"}}'), ('failed', 'turn'))

    def test_replay_preserves_failure_even_if_a_new_turn_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            target = Target(Mock(), Mock(), -1, thread='thread', rollout=path, recovery=Recovery(phase='verifying'))
            records = [
                {'type': 'task_complete', 'turn_id': 'failed', 'error': {'message': 'stream disconnected before completion: server error', 'codex_error_info': 'other'}},
                {'type': 'task_started', 'turn_id': 'next'},
            ]
            path.write_text(''.join(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'type': 'event_msg', 'payload': p}) + '\n' for p in records))
            with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'active', 0, 0, int((time.time() - 10) * 1000))):
                target.replay()
            self.assertEqual(target.failures, [('stream', 'turn:failed')])
            self.assertFalse(target.recovery.progressed)


if __name__ == '__main__':
    unittest.main()
