use std::time::Duration;

use anyhow::Result;
use serde_json::json;
use tokio::time::Instant;

use super::{Session, now};
use crate::monitor::policy::{Goal, Phase, Turn};

impl Session {
    pub(super) async fn timers(&mut self) -> Result<()> {
        let pending: Vec<_> = self
            .targets
            .iter()
            .filter(|(_, t)| {
                t.inspect_at.is_some_and(|d| d <= Instant::now())
                    || t.deadline.is_some_and(|d| d <= Instant::now())
            })
            .map(|(id, _)| id.clone())
            .collect();
        for thread in pending {
            if self.targets[&thread]
                .inspect_at
                .is_some_and(|d| d <= Instant::now())
            {
                self.targets.get_mut(&thread).unwrap().inspect_at = None;
                self.inspect(&thread).await?;
            }
            if self.targets[&thread]
                .deadline
                .is_some_and(|d| d <= Instant::now())
            {
                self.targets.get_mut(&thread).unwrap().deadline = None;
                if self.targets[&thread].recovery.phase == Phase::Waiting {
                    self.resume(&thread).await?;
                } else if self.targets[&thread].recovery.phase == Phase::Sent {
                    self.targets.get_mut(&thread).unwrap().recovery.phase = Phase::Halted;
                    self.notify(
                        &thread,
                        "Codex Goal Recovery Stopped",
                        "再開結果が不明なため、追加の操作を停止しました。",
                    );
                }
            }
        }
        Ok(())
    }

    async fn inspect(&mut self, thread: &str) -> Result<()> {
        let turn = self.latest_turn(thread).await?;
        let Some(turn) = turn else {
            return Ok(());
        };
        let target = self.targets.get_mut(thread).unwrap();
        let halted = target.recovery.phase == Phase::Halted;
        let notification = if target.recovery.complete(&turn) {
            target.deadline = None;
            Some(("Codex Resumed", "再開後の最初のターンが正常終了しました。"))
        } else if turn.id == target.recovery.last_turn {
            None
        } else if target.recovery.schedule(&turn, target.goal.as_ref(), now()) {
            target.deadline = Some(
                Instant::now() + Duration::from_secs(target.recovery.due.saturating_sub(now())),
            );
            Some((
                "Codex Recovery Scheduled",
                "Capacityエラーまたは通信切断からの再開を待機します。",
            ))
        } else if !halted && target.recovery.phase == Phase::Halted {
            target.deadline = None;
            Some((
                "Codex Recovery Stopped",
                "復旧失敗が上限に達したため停止しました。",
            ))
        } else if matches!(target.recovery.phase, Phase::Sent | Phase::Verifying)
            && matches!(turn.status.as_str(), "failed" | "interrupted")
        {
            target.recovery.phase = Phase::Watching;
            target.deadline = None;
            Some((
                "Codex Recovery Failed",
                "再開後のターンが正常終了しませんでした。",
            ))
        } else {
            None
        };
        if let Some((title, detail)) = notification {
            self.notify(thread, title, detail);
        }
        Ok(())
    }

    async fn latest_turn(&mut self, thread: &str) -> Result<Option<Turn>> {
        let result = self
            .client
            .request(
                "thread/turns/list",
                json!({"threadId": thread, "limit": 1, "itemsView": "notLoaded"}),
            )
            .await?;
        let turns: Vec<Turn> = serde_json::from_value(result["data"].clone())?;
        Ok(turns.into_iter().next())
    }

    async fn resume(&mut self, thread: &str) -> Result<()> {
        let target = &self.targets[thread];
        if !target.recovery.eligible(target.goal.as_ref(), now()) {
            return Ok(());
        }
        let metadata = self
            .client
            .request("thread/read", json!({"threadId": thread}))
            .await?;
        if !matches!(
            metadata["thread"]["status"]["type"].as_str(),
            Some("idle" | "systemError")
        ) {
            return Ok(());
        }
        let result = self
            .client
            .request("thread/goal/get", json!({"threadId": thread}))
            .await?;
        let goal: Option<Goal> = serde_json::from_value(result["goal"].clone())?;
        let target = &self.targets[thread];
        let same_goal = match (&goal, &target.goal) {
            (Some(current), Some(previous)) => current.same_goal(previous),
            (None, None) => true,
            _ => false,
        };
        if !same_goal || !target.recovery.eligible(goal.as_ref(), now()) {
            return Ok(());
        }
        let Some(turn) = self.latest_turn(thread).await? else {
            return Ok(());
        };
        let target = self.targets.get_mut(thread).unwrap();
        if turn.id != target.recovery.last_turn || !turn.retryable(goal.as_ref(), now()) {
            target.recovery.phase = Phase::Watching;
            return Ok(());
        }
        target.recovery.phase = Phase::Sent;
        target.deadline = Some(Instant::now() + Duration::from_secs(45));
        if goal.is_some() {
            let result = self
                .client
                .request(
                    "thread/goal/set",
                    json!({"threadId": thread, "status": "active", "origin": "automatic"}),
                )
                .await?;
            self.goal(
                thread,
                serde_json::from_value(result["goal"].clone())?,
                None,
                false,
            );
        } else {
            self.client
                .request(
                    "thread/resume",
                    json!({"threadId": thread, "excludeTurns": true}),
                )
                .await?;
            self.client
                .request(
                    "turn/start",
                    json!({
                        "threadId": thread,
                        "input": [{"type": "text", "text": "continue"}],
                    }),
                )
                .await?;
            let target = self.targets.get_mut(thread).unwrap();
            target.recovery.phase = Phase::Verifying;
            target.deadline = None;
            self.notify(thread, "Codex Resume Started", "作業の続きを再開しました。");
        }
        Ok(())
    }
}

#[cfg(all(test, unix))]
mod tests;
