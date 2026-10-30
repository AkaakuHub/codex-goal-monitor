mod recovery;

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
    policy::{Goal, Phase, Recovery},
};
use crate::{config::Settings, notifications::Notification};

struct Target {
    goal: Option<Goal>,
    recovery: Recovery,
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
        } else {
            self.targets.insert(
                thread.into(),
                Target {
                    goal: None,
                    recovery: Recovery::default(),
                    inspect_at: Some(Instant::now() + Duration::from_millis(500)),
                    deadline: None,
                },
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
                    } else if matches!(
                        params["status"]["type"].as_str(),
                        Some("idle" | "systemError")
                    ) {
                        self.snapshot(thread).await?;
                        let Some(target) = self.targets.get_mut(thread) else {
                            return Ok(());
                        };
                        target.inspect_at = Some(Instant::now() + Duration::from_millis(500));
                        if target.deadline.is_none()
                            && target.recovery.eligible(target.goal.as_ref(), now())
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
        eprintln!("{title}: {thread}");
        let _ = self.notifications.try_send(Notification {
            settings: self.settings.clone(),
            thread: thread.into(),
            title,
            detail,
        });
    }

    fn goal(&mut self, thread: &str, goal: Goal, turn: Option<String>, initial: bool) {
        if self.targets.get(thread).is_some_and(|t| {
            t.goal
                .as_ref()
                .is_none_or(|current| !current.same_goal(&goal))
        }) {
            self.targets.remove(thread);
        }
        let previous = self
            .targets
            .get(thread)
            .and_then(|t| t.goal.as_ref().map(|goal| goal.status.clone()))
            .unwrap_or_default();
        let target = self.targets.entry(thread.into()).or_insert_with(|| Target {
            goal: Some(goal.clone()),
            recovery: Recovery::default(),
            inspect_at: None,
            deadline: None,
        });
        let status = goal.status.clone();
        target.goal = Some(goal);
        match status.as_str() {
            "complete" | "usageLimited" | "paused" | "budgetLimited" => {
                target.deadline = None;
                target.inspect_at = None;
                target.recovery.phase = Phase::Watching;
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
}
