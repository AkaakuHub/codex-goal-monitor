import time
from collections.abc import Callable

from . import adapter, tmux
from .identity import inspect_thread
from .input import send_command
from .processes import read_process
from .state import State
from .tracking import Target, binding


async def recover(target: Target, screen: str, notify: Callable[[Target, str, str], None], state: State, max_failures: int) -> None:
    recovery = target.recovery
    goal = adapter.read_goal(target.process.home, target.thread or '')
    now = time.time()
    if not goal:
        return
    if recovery.error and recovery.phase == 'watching' and (now - recovery.error_time > 1800 or goal.status == 'active' and now - recovery.error_time > 60):
        recovery.cancel()
        notify(target, 'Codex Goal Recovery Failed', 'Reason: Capacityエラーと現在のstalled状態の関連を確認できないため自動入力を見送りました。')
        return
    if goal.status in ('paused', 'usage_limited', 'budget_limited', 'complete'):
        recovery.cancel()
        return
    if recovery.phase == 'verifying':
        if goal.status == 'active' and recovery.progressed:
            recovery.success()
            notify(target, 'Codex Goal Resumed', 'Action: /goal resume\nResult: Success (first resumed turn completed)')
        return
    if recovery.phase in ('sent', 'confirming'):
        if goal.status == 'active' and ('Pursuing goal' in screen or recovery.started and recovery.busy):
            recovery.phase = 'verifying'
            notify(target, 'Codex Goal Resume Started', 'Action: /goal resume\nResult: Goal active; awaiting first completed turn')
        elif now >= recovery.deadline:
            recovery.failures += 1
            recovery.halted = True
            recovery.cancel()
            notify(target, 'Codex Goal Recovery Failed', 'Reason: Goalがactiveへ変化したことを確認できませんでした。自動入力を停止しました。')
        elif recovery.phase == 'sent' and goal.status == 'blocked' and adapter.resume_selected(screen):
            current = read_process(target.process.pid)
            fresh = await tmux.panes(target.pane.socket)
            pane = next((p for p in fresh if p.pane == target.pane.pane), None)
            if current == target.process and pane and binding(current, pane) == (target.thread, target.rollout):
                recovery.phase = 'confirming'
                state.save()
                await tmux.command(pane.socket, 'send-keys', '-t', pane.pane, 'Enter')
        return
    if not recovery.eligible(goal.status, goal.goal_id, now):
        return
    if recovery.busy or target.pane.mode or not adapter.idle_stalled(screen, target.pane.cursor_x, target.pane.cursor_y):
        if now - recovery.due > 300:
            recovery.cancel()
            notify(target, 'Codex Goal Recovery Failed', 'Reason: 入力欄・メニュー・処理中の状態を確認できず、自動入力を見送りました。')
        return
    if recovery.failures >= max_failures or recovery.resumes >= 5:
        recovery.halted = True
        notify(target, 'Codex Goal Recovery Failed', 'Reason: 同じGoalの自動復旧が5回に達しました。自動入力を停止しました。')
        return
    current = read_process(target.process.pid)
    fresh = await tmux.panes(target.pane.socket)
    pane = next((p for p in fresh if p.pane == target.pane.pane), None)
    latest = adapter.read_goal(target.process.home, target.thread or '')
    if current != target.process or not pane or pane.mode or not latest or latest != goal:
        return
    identity = binding(current, pane)
    if identity != (target.thread, target.rollout):
        if not target.proof_at or await inspect_thread(target, target.thread) != (target.thread, target.rollout):
            recovery.halted = True
            recovery.cancel()
            notify(target, 'Codex Goal Recovery Failed', 'Reason: 再開直前に現在のThreadを再確認できないため自動再開しません。')
            return
        pane = target.pane
    _, current_screen = await tmux.command(pane.socket, 'capture-pane', '-p', '-t', pane.pane)
    if not adapter.idle_stalled(current_screen, pane.cursor_x, pane.cursor_y):
        return
    recovery.resumes += 1
    recovery.goal_id = goal.goal_id
    recovery.phase = 'sent'
    recovery.deadline = now + 45
    recovery.started = False
    state.save()
    if not await send_command(target, '/goal resume', goal):
        recovery.halted = True
        recovery.cancel()
        notify(target, 'Codex Goal Recovery Failed', 'Reason: 再開コマンドの送信中に入力欄またはGoal状態が変化したため、追加の操作を停止しました。')
