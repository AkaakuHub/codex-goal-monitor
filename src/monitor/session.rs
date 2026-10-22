use std::{
    collections::HashMap,
    sync::mpsc::SyncSender,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use anyhow::Result;
use serde_json::{Value, json};
use tokio::time::Instant;

use super::{
    client::{Client, RejectedRequest},
    policy::{Goal, Phase, Recovery, Turn},
};
use crate::{config::Settings, notifications::Notification};

struct Target {
    goal: Goal,
    recovery: Recovery,
    turn: Option<String>,
    inspect_at: Option<Instant>,
    deadline: Option<Instant>,
}

pub struct Session {
    client: Client,
    settings: Settings,
    notifications: SyncSender<Notification>,
    targets: HashMap<String, Target>,
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

impl Session {
    pub fn new(
        client: Client,
        settings: Settings,
        notifications: SyncSender<Notification>,
    ) -> Self {
        Self {
            client,
            settings,
            notifications,
            targets: HashMap::new(),
        }
    }

    pub async fn run(&mut self) -> Result<()> {
        let mut cursor = Value::Null;
        loop {
            let result = self
                .client
                .request("thread/loaded/list", json!({"cursor": cursor}))
                .await?;
            if let Some(threads) = result["data"].as_array() {
                for thread in threads.iter().filter_map(Value::as_str) {
                    if let Err(error) = self.snapshot(thread).await
                        && !error.is::<RejectedRequest>()
                    {
                        return Err(error);
                    }
                }
            }
            cursor = result["nextCursor"].clone();
            if cursor.is_null() {
                break;
            }
        }
        loop {
            let deadline = self
                .targets
                .values()
                .flat_map(|t| [t.inspect_at, t.deadline])
                .flatten()
                .min();
            let result = tokio::select! {
                event = self.client.next() => self.event(event?).await,
                _ = async {
                    match deadline {
                        Some(deadline) => tokio::time::sleep_until(deadline).await,
                        None => std::future::pending::<()>().await,
                    }
                } => self.timers().await,
            };
            if let Err(error) = result
                && !error.is::<RejectedRequest>()
            {
                return Err(error);
            }
        }
    }

    async fn snapshot(&mut self, thread: &str) -> Result<()> {
        if self.targets.contains_key(thread) {
            return Ok(());
        }
        let result = self
            .client
            .request("thread/goal/get", json!({"threadId": thread}))
            .await?;
        if !result["goal"].is_null() {
            self.goal(
                thread,
                serde_json::from_value(result["goal"].clone())?,
                None,
                true,
            );
        }
        Ok(())
    }

    async fn event(&mut self, event: Value) -> Result<()> {
        let params = &event["params"];
        let method = event["method"].as_str().unwrap_or("");
        if method == "thread/started" {
            if let Some(thread) = params["thread"]["id"].as_str() {
                self.snapshot(thread).await?;
            }
        } else if let Some(thread) = params["threadId"].as_str() {
            match method {
                "thread/goal/updated" => self.goal(
                    thread,
                    serde_json::from_value(params["goal"].clone())?,
                    params["turnId"].as_str().map(str::to_owned),
                    false,
                ),
                "thread/goal/cleared" | "thread/closed" => {
                    self.targets.remove(thread);
                }
                "thread/status/changed" => {
                    if params["status"]["type"] == "notLoaded" {
                        self.targets.remove(thread);
                    } else if let Some(target) = self.targets.get_mut(thread)
                        && matches!(
                            params["status"]["type"].as_str(),
                            Some("idle" | "systemError")
                        )
                    {
                        if matches!(target.recovery.phase, Phase::Sent | Phase::Verifying) {
                            target.inspect_at = Some(Instant::now() + Duration::from_millis(500));
                        } else if target.deadline.is_none()
                            && target.recovery.eligible(&target.goal, now())
                        {
                            target.deadline = Some(Instant::now());
                        }
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn notify(&self, thread: &str, title: &'static str, detail: &'static str) {
        let _ = self.notifications.try_send(Notification {
            settings: self.settings.clone(),
            thread: thread.into(),
            title,
            detail,
        });
    }

    fn goal(&mut self, thread: &str, goal: Goal, turn: Option<String>, initial: bool) {
        if self
            .targets
            .get(thread)
            .is_some_and(|t| !t.goal.same_goal(&goal))
        {
            self.targets.remove(thread);
        }
        let previous = self
            .targets
            .get(thread)
            .map(|t| t.goal.status.clone())
            .unwrap_or_default();
        let target = self.targets.entry(thread.into()).or_insert_with(|| Target {
            goal: goal.clone(),
            recovery: Recovery::default(),
            turn: None,
            inspect_at: None,
            deadline: None,
        });
        target.goal = goal;
        if turn.is_some() {
            target.turn = turn.clone();
        }
        match target.goal.status.as_str() {
            "complete" | "usageLimited" | "paused" | "budgetLimited" => {
                target.deadline = None;
                target.inspect_at = None;
                target.recovery.phase = Phase::Watching;
                let status = target.goal.status.clone();
                if !initial && previous != status {
                    if status == "complete" {
                        self.notify(thread, "Codex Goal Completed", "Goalが完了しました。");
                    } else if status == "usageLimited" {
                        self.notify(thread, "Codex Goal Usage Limited", "利用上限に達しました。");
                    }
                }
            }
            "blocked"
                if previous != "blocked" || turn.as_deref() != Some(&target.recovery.last_turn) =>
            {
                target.inspect_at = Some(Instant::now() + Duration::from_millis(500));
            }
            "active" => {
                let started = target.recovery.phase == Phase::Sent;
                if started {
                    target.recovery.phase = Phase::Verifying;
                    target.deadline = None;
                } else if target.recovery.phase == Phase::Waiting {
                    target.recovery.phase = Phase::Watching;
                    target.deadline = None;
                }
                if target.recovery.phase == Phase::Verifying && turn.is_some() {
                    target.inspect_at = Some(Instant::now() + Duration::from_millis(500));
                }
                if started {
                    self.notify(
                        thread,
                        "Codex Goal Resume Started",
                        "最初のターンの完了を確認しています。",
                    );
                }
            }
            _ => {}
        }
    }

    async fn timers(&mut self) -> Result<()> {
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
        let result = self
            .client
            .request(
                "thread/turns/list",
                json!({"threadId": thread, "limit": 2, "itemsView": "notLoaded"}),
            )
            .await?;
        let turns: Vec<Turn> = serde_json::from_value(result["data"].clone())?;
        let target = self.targets.get_mut(thread).unwrap();
        let mut notification = None;
        for turn in turns {
            if target.goal.status == "blocked"
                && target.turn.as_ref().is_none_or(|id| *id == turn.id)
            {
                let previous = &target.recovery.phase;
                let halted = *previous == Phase::Halted;
                if target.recovery.schedule(&turn, &target.goal, now()) {
                    target.deadline = Some(
                        Instant::now()
                            + Duration::from_secs(target.recovery.due.saturating_sub(now())),
                    );
                    notification = Some((
                        "Codex Goal Recovery Scheduled",
                        "Capacityエラーまたは通信切断からの再開を待機します。",
                    ));
                } else if !halted && target.recovery.phase == Phase::Halted {
                    target.deadline = None;
                    notification = Some((
                        "Codex Goal Recovery Stopped",
                        "トークンを消費する復旧失敗が5回続いたため停止しました。",
                    ));
                } else if matches!(target.recovery.phase, Phase::Sent | Phase::Verifying) {
                    target.recovery.phase = Phase::Watching;
                    target.deadline = None;
                    notification = Some((
                        "Codex Goal Recovery Failed",
                        "再開後のターンが正常終了しませんでした。",
                    ));
                }
                break;
            }
            if turn.id == target.recovery.last_turn {
                break;
            }
            if target.recovery.complete(&turn) {
                target.deadline = None;
                notification = Some((
                    "Codex Goal Resumed",
                    "再開後の最初のターンが正常終了しました。",
                ));
                break;
            }
        }
        if let Some((title, detail)) = notification {
            self.notify(thread, title, detail);
        }
        Ok(())
    }

    async fn resume(&mut self, thread: &str) -> Result<()> {
        let target = &self.targets[thread];
        if !target.recovery.eligible(&target.goal, now()) {
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
        let Some(goal): Option<Goal> = serde_json::from_value(result["goal"].clone())? else {
            return Ok(());
        };
        let target = &self.targets[thread];
        if !goal.same_goal(&target.goal) || !target.recovery.eligible(&goal, now()) {
            return Ok(());
        }
        let target = self.targets.get_mut(thread).unwrap();
        target.recovery.phase = Phase::Sent;
        target.deadline = Some(Instant::now() + Duration::from_secs(45));
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
        Ok(())
    }
}
