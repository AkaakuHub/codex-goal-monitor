import json
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from monitor.adapter import Goal, event
from monitor.evaluation import evaluate
from monitor.policy import Recovery
from monitor.processes import Process
from monitor.recovery import recover
from monitor.tmux import Pane
from monitor.tracking import Target


class ResumedTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_alone_is_started_not_success(self):
        target = Mock()
        target.recovery = Recovery(phase='sent', started=True, busy=True)
        target.thread = 'thread'
        notify = Mock()
        with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'active', 0, 0, 0)):
            await recover(target, 'Pursuing goal', notify, Mock())
        self.assertEqual(target.recovery.phase, 'verifying')
        self.assertEqual(notify.call_args.args[1], 'Codex Goal Resume Started')

    async def test_success_requires_a_completed_resumed_turn(self):
        target = Mock()
        target.recovery = Recovery(phase='verifying')
        notify = Mock()
        with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'active', 0, 0, 0)):
            await recover(target, 'Pursuing goal', notify, Mock())
            notify.assert_not_called()
            target.recovery.progressed = True
            await recover(target, 'Pursuing goal', notify, Mock())
        self.assertEqual(notify.call_args.args[1], 'Codex Goal Resumed')
        self.assertEqual(target.recovery.phase, 'watching')

    async def test_stream_failure_is_reported_without_input_to_active_goal(self):
        for status in ('active', 'blocked', 'paused', 'complete', 'budget_limited', 'usage_limited'):
            with self.subTest(status=status):
                pane = Pane(Path('/socket'), '%1', 'test', '0', '0', 10, '/tty', '', False, 2, 2, False)
                process = Process(10, 1, 'start', '/tty', Path('/home'))
                recovery = Recovery(phase='verifying', error='original', goal_id='goal', attempt=1)
                target = Target(pane, process, -1, thread='thread', rollout=Path('/rollout'), recovery=recovery, capture_due=False, failures=[('stream', 'turn:failure')])
                monitor = Mock()
                monitor.servers = [pane.socket]
                monitor.targets = {pane.key: target}
                monitor.delays = [30, 60]
                monitor.config = {}
                with patch('monitor.evaluation.tmux.panes', new=AsyncMock(return_value=[pane])), patch('monitor.evaluation.read_process', return_value=process), patch('monitor.evaluation.binding', return_value=('thread', target.rollout)), patch('monitor.adapter.read_goal', return_value=Goal('goal', status, 0, 0, 0)), patch.object(Target, 'replay', return_value=[]), patch('monitor.evaluation.tmux.command', new=AsyncMock()) as command:
                    await evaluate(monitor)
                command.assert_not_called()
                titles = [call.args[1] for call in monitor.notify.call_args_list]
                self.assertNotIn('Codex Goal Resumed', titles)
                if status == 'blocked':
                    self.assertIn('Codex Stream Error', titles)
                    self.assertEqual(recovery.error, 'turn:failure')
                    self.assertGreater(recovery.due, time.time() + 50)
                elif status == 'active':
                    self.assertIn('Codex Goal Recovery Failed', titles)
                    self.assertIsNone(recovery.error)
                else:
                    self.assertNotIn('Codex Goal Recovery Failed', titles)
                    self.assertIsNone(recovery.error)

    async def test_removed_goal_does_not_report_recovery_failure(self):
        pane = Pane(Path('/socket'), '%1', 'test', '0', '0', 10, '/tty', '', False, 2, 2, False)
        process = Process(10, 1, 'start', '/tty', Path('/home'))
        recovery = Recovery(error='original', goal_id='goal')
        target = Target(pane, process, -1, thread='thread', rollout=Path('/rollout'), recovery=recovery, capture_due=False)
        monitor = Mock(servers=[pane.socket], targets={pane.key: target})
        with patch('monitor.evaluation.tmux.panes', new=AsyncMock(return_value=[pane])), patch('monitor.evaluation.read_process', return_value=process), patch('monitor.evaluation.binding', return_value=('thread', target.rollout)), patch('monitor.adapter.read_goal', return_value=None), patch.object(Target, 'replay', return_value=[]):
            await evaluate(monitor)
        monitor.notify.assert_not_called()
        self.assertIsNone(recovery.error)

    async def test_capacity_recurring_before_active_observation_is_retried(self):
        pane = Pane(Path('/socket'), '%1', 'test', '0', '0', 10, '/tty', '', False, 2, 2, False)
        process = Process(10, 1, 'start', '/tty', Path('/home'))
        recovery = Recovery(phase='sent', error='original', goal_id='goal', attempt=1, seen={'original'})
        target = Target(pane, process, -1, thread='thread', rollout=Path('/rollout'), recovery=recovery, capture_due=False)
        monitor = Mock()
        monitor.servers = [pane.socket]
        monitor.targets = {pane.key: target}
        monitor.delays = [30, 60]
        monitor.config = {}
        with patch('monitor.evaluation.tmux.panes', new=AsyncMock(return_value=[pane])), patch('monitor.evaluation.read_process', return_value=process), patch('monitor.evaluation.binding', return_value=('thread', target.rollout)), patch('monitor.adapter.read_goal', return_value=Goal('goal', 'blocked', 0, 0, 0)), patch.object(Target, 'replay', return_value=['turn:new']):
            await evaluate(monitor)
        self.assertEqual(recovery.error, 'turn:new')
        self.assertEqual(recovery.phase, 'watching')
        self.assertGreater(recovery.due, time.time() + 50)

    async def test_token_wasting_loop_stops_before_sending_input(self):
        target = Mock()
        target.recovery = Recovery(error='error', goal_id='goal', due=time.time() - 1, error_time=time.time(), wasted_turns=5)
        target.pane.mode = False
        target.pane.cursor_x = 2
        target.pane.cursor_y = 0
        notify = Mock()
        with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'blocked', 0, 0, 0)), patch('monitor.recovery.tmux.command', new=AsyncMock()) as command:
            await recover(target, '›\nGoal stalled (/goal resume)', notify, Mock())
        self.assertTrue(target.recovery.halted)
        command.assert_not_called()
        self.assertEqual(notify.call_args.args[1], 'Codex Goal Recovery Failed')

    def test_repeated_tool_output_is_not_new_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            target = Target(Mock(), Mock(), -1, thread='thread', rollout=path)
            def record(output, call):
                return json.dumps({'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': call, 'output': output}}) + '\n'
            path.write_text(record('unchanged output', 'first'))
            with patch('monitor.adapter.read_goal', return_value=None):
                target.replay(initial=True)
                self.assertFalse(target.turn_work)
                with path.open('a') as file:
                    file.write(record('unchanged output', 'different-id'))
                target.replay()
                self.assertFalse(target.turn_work)
                with path.open('a') as file:
                    file.write(record('changed output', 'new'))
                target.replay()
                self.assertTrue(target.turn_work)

    def test_failed_and_aborted_turns_are_not_successful(self):
        stream = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn', 'error': {'codex_error_info': 'other', 'message': 'stream disconnected before completion: An error occurred while processing your request.'}}}
        self.assertEqual(event(json.dumps(stream).encode()), ('stream', 'turn'))
        stream['payload']['error']['message'] = 'Error running remote compact task: stream disconnected before completion: An error occurred while processing your request.'
        self.assertEqual(event(json.dumps(stream).encode()), ('stream', 'turn'))
        stream['payload']['error']['message'] = 'Error running remote compact task: Permission denied'
        self.assertEqual(event(json.dumps(stream).encode()), ('failed', 'turn'))
        stream['payload']['error']['message'] = 'Permission denied'
        self.assertEqual(event(json.dumps(stream).encode()), ('failed', 'turn'))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"turn_aborted","turn_id":"turn"}}'), ('aborted', 'turn'))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn","error":{"status_code":429,"message":"rate limit"}}}'), ('capacity', 'turn'))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn","error":{"message":"HTTP 429 Too Many Requests"}}}'), ('capacity', 'turn'))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"user_message","message":"429"}}'), ('user', None))
        self.assertEqual(event(b'{"type":"event_msg","payload":{"type":"error","will_retry":true,"message":"stream disconnected before completion: retrying"}}'), ('', None))

    def test_remote_compact_failure_reaches_the_recovery_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            message = 'Error running remote compact task: stream disconnected before completion: An error occurred while processing your request.'
            record = {'timestamp': datetime.now(UTC).isoformat(), 'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'compact-turn', 'error': {'message': message, 'codex_error_info': 'other'}}}
            path.write_text(json.dumps(record) + '\n')
            target = Target(Mock(), Mock(), -1, thread='thread', rollout=path)
            with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'blocked', 0, 0, int((time.time() - 10) * 1000))):
                target.replay()
            self.assertEqual(target.failures, [('stream', 'turn:compact-turn')])
            self.assertFalse(target.recovery.busy)

    def test_manual_abort_is_not_a_failed_or_completed_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            record = {'timestamp': datetime.now(UTC).isoformat(), 'type': 'event_msg', 'payload': {'type': 'turn_aborted', 'turn_id': 'manual'}}
            path.write_text(json.dumps(record) + '\n')
            target = Target(Mock(), Mock(), -1, thread='thread', rollout=path, recovery=Recovery(phase='verifying', busy=True))
            with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'paused', 0, 0, int((time.time() - 10) * 1000))):
                self.assertEqual(target.replay(), [])
            self.assertEqual(target.failures, [])
            self.assertFalse(target.recovery.busy)
            self.assertFalse(target.recovery.progressed)

    def test_replay_preserves_failure_even_if_a_new_turn_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            target = Target(Mock(), Mock(), -1, thread='thread', rollout=path, recovery=Recovery(phase='verifying'))
            records = [
                {'type': 'task_complete', 'turn_id': 'failed', 'error': {'message': 'stream disconnected before completion: server error', 'codex_error_info': 'other'}},
                {'type': 'task_started', 'turn_id': 'next'},
            ]
            path.write_text(''.join(json.dumps({'timestamp': datetime.now(UTC).isoformat(), 'type': 'event_msg', 'payload': p}) + '\n' for p in records))
            with patch('monitor.adapter.read_goal', return_value=Goal('goal', 'active', 0, 0, int((time.time() - 10) * 1000))):
                target.replay()
            self.assertEqual(target.failures, [('stream', 'turn:failed')])
            self.assertFalse(target.recovery.progressed)


if __name__ == '__main__':
    unittest.main()
