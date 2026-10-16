import asyncio
import time
from typing import TYPE_CHECKING

from . import adapter, tmux
from .identity import inspect_thread, stable_title
from .processes import read_process
from .recovery import recover
from .tracking import binding

if TYPE_CHECKING:
    from .service import Monitor


async def evaluate(monitor: "Monitor") -> None:
    results = await asyncio.gather(*(tmux.panes(s) for s in monitor.servers))
    current = {pane.key: pane for group in results for pane in group}
    for target in list(monitor.targets.values()):
        if target.pane.key not in current:
            monitor.wake()
            continue
        target.pane = current[target.pane.key]
        if read_process(target.process.pid) != target.process:
            monitor.wake()
            continue
        identity = binding(target.process, target.pane)
        if identity and identity != (target.thread, target.rollout):
            thread, path = identity
            target.bind(thread, path, monitor.state.get(f'{target.process.home}:{thread}'))
        elif not identity and target.thread and (not target.proof_at or stable_title(target.pane.title) != target.proof_title) and target.recovery.phase == 'watching':
            target.thread = None
            target.rollout = None
        if not identity and target.capture_due and not target.uncertain_notified:
            _, identity_screen = await tmux.command(target.pane.socket, 'capture-pane', '-p', '-t', target.pane.pane)
            shown_thread = adapter.status_thread(identity_screen)
            pending = monitor.state.values.get(f'{target.process.home}:{shown_thread}') if shown_thread else None
            capacity = adapter.terminal_capacity(identity_screen, target.pane.cursor_y)
            terminal_goal = any('Goal achieved' in line or 'Goal hit usage limits' in line for line in identity_screen.splitlines()[target.pane.cursor_y + 1:target.pane.cursor_y + 6])
            if adapter.status_idle(identity_screen, target.pane.cursor_x, target.pane.cursor_y) and (capacity or pending and pending.error or terminal_goal):
                inspected = await inspect_thread(target)
                if inspected:
                    thread, path = inspected
                    target.bind(thread, path, monitor.state.get(f'{target.process.home}:{thread}'))
                    verified_goal = adapter.read_goal(target.process.home, thread)
                    if capacity and verified_goal and verified_goal.status == 'blocked':
                        target.pending_capacity = target.pending_capacity or (f'turn:{target.turn_id}' if target.turn_id else f'tui:{verified_goal.goal_id}')
                else:
                    monitor.notify(target, 'Codex Goal Recovery Failed', 'Reason: 読み取り専用の/statusから現在のThreadを確定できないため自動再開しません。')
                    target.uncertain_notified = True
        if not target.thread:
            target.capture_due = False
            continue
        goal = adapter.read_goal(target.process.home, target.thread)
        if not goal:
            target.replay()
            target.failures.clear()
            target.pending_capacity = None
            target.recovery.cancel()
            continue
        recovery = target.recovery
        if (target.last_goal_id or recovery.goal_id) and (target.last_goal_id or recovery.goal_id) != goal.goal_id:
            recovery.success()
            recovery.goal_id = ''
            recovery.halted = False
            recovery.resumes = 0
            target.work_seen.clear()
        target.last_goal_id = goal.goal_id
        if goal.status != target.status:
            if goal.status == 'complete' and f'complete:{goal.goal_id}' not in recovery.seen:
                monitor.notify(target, 'Codex Goal Completed')
                recovery.seen.add(f'complete:{goal.goal_id}')
            elif goal.status == 'usage_limited':
                monitor.notify(target, 'Codex Goal Usage Limited', 'Action: Notify only')
            target.status = goal.status
        errors = target.replay()
        for kind, identity in target.failures:
            if identity in recovery.seen:
                continue
            recovery.failed_turn(goal.tokens, target.turn_work)
            recovery.cancel()
            if goal.status in ('paused', 'complete', 'budget_limited', 'usage_limited'):
                recovery.seen.add(identity)
                continue
            if kind == 'stream' and goal.status == 'blocked' and recovery.capacity(identity, time.time(), monitor.delays):
                recovery.goal_id = goal.goal_id
                monitor.notify(target, 'Codex Stream Error', 'Action: Resume scheduled')
            else:
                recovery.seen.add(identity)
                monitor.notify(target, 'Codex Goal Recovery Failed', 'Reason: ターンが通信エラーまたは実行エラーで終了しました。Goalがblockedでない場合は自動入力を行いません。')
        target.failures.clear()
        if target.pending_capacity:
            errors.append(target.pending_capacity)
            target.pending_capacity = None
        screen = ''
        if target.capture_due and (goal.status == 'blocked' or recovery.phase != 'watching'):
            _, screen = await tmux.command(target.pane.socket, 'capture-pane', '-p', '-t', target.pane.pane)
            if goal.status == 'blocked' and adapter.terminal_capacity(screen, target.pane.cursor_y) and time.time() * 1000 - goal.updated < 1800000:
                errors.append(f'turn:{target.turn_id}' if target.turn_id else f'tui:{goal.goal_id}')
                recovery.busy = False
        target.capture_due = False
        for error in errors:
            if recovery.phase != 'watching' and error not in recovery.seen:
                recovery.failed_turn(goal.tokens, target.turn_work)
                recovery.cancel()
                monitor.notify(target, 'Codex Goal Recovery Failed', 'Reason: 再開後のターンでCapacityエラーが再発しました。待機時間を延ばして再試行します。')
            if recovery.error is not None:
                recovery.seen.add(error)
            elif goal.status in ('blocked', 'active') and recovery.capacity(error, time.time(), monitor.delays):
                recovery.goal_id = goal.goal_id
                monitor.notify(target, 'Codex Capacity Error', 'Action: Resume scheduled')
        if goal.status in ('complete', 'paused', 'budget_limited', 'usage_limited'):
            recovery.cancel()
        if recovery.error and time.time() >= recovery.due or recovery.phase != 'watching':
            if not screen:
                _, screen = await tmux.command(target.pane.socket, 'capture-pane', '-p', '-t', target.pane.pane)
            await recover(target, screen, monitor.notify, monitor.state)
    monitor.state.save()
    monitor.state.status([{'tmux': t.pane.label, 'socket': str(t.pane.socket), 'pane_id': t.pane.pane, 'pid': t.process.pid, 'thread_id': t.thread, 'goal': t.status or 'unknown', 'phase': t.recovery.phase, 'halted': t.recovery.halted, 'output_monitor': 'control-subscription'} for t in monitor.targets.values()])

