use serde::Deserialize;
use serde_json::Value;

const DELAYS: [u64; 5] = [30, 60, 120, 300, 600];

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Goal {
    pub status: String,
    pub created_at: u64,
    pub objective: String,
    pub tokens_used: u64,
}

impl Goal {
    pub fn same_goal(&self, other: &Self) -> bool {
        self.created_at == other.created_at && self.objective == other.objective
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Turn {
    pub id: String,
    pub status: String,
    pub started_at: Option<u64>,
    pub completed_at: Option<u64>,
    pub error: Option<Value>,
}

impl Turn {
    pub fn retryable(&self, goal: &Goal, now: u64) -> bool {
        let (Some(started), Some(completed)) = (self.started_at, self.completed_at) else {
            return false;
        };
        if self.status != "failed"
            || started < goal.created_at
            || completed < started
            || completed > now
            || now - completed > 1800
        {
            return false;
        }
        let Some(error) = &self.error else {
            return false;
        };
        let info = &error["codexErrorInfo"];
        if matches!(
            info.as_str(),
            Some(
                "serverOverloaded"
                    | "rateLimitExceeded"
                    | "responseStreamDisconnected"
                    | "responseStreamConnectionFailed"
            )
        ) {
            return true;
        }
        if info.as_object().is_some_and(|info| {
            info.iter().any(|(key, value)| {
                matches!(
                    key.as_str(),
                    "responseStreamDisconnected" | "responseStreamConnectionFailed"
                ) || value["httpStatusCode"] == 429
            })
        }) {
            return true;
        }
        error["message"].as_str().is_some_and(|message| {
            message.starts_with("stream disconnected before completion:")
                || message.starts_with(
                    "Error running remote compact task: stream disconnected before completion:",
                )
        })
    }
}

#[derive(Default, Debug, PartialEq, Eq)]
pub enum Phase {
    #[default]
    Watching,
    Waiting,
    Sent,
    Verifying,
    Halted,
}

#[derive(Default)]
pub struct Recovery {
    pub phase: Phase,
    pub last_turn: String,
    pub due: u64,
    pub error_time: u64,
    attempt: usize,
    baseline: u64,
    wasted: u8,
}

impl Recovery {
    pub fn schedule(&mut self, turn: &Turn, goal: &Goal, now: u64) -> bool {
        if self.phase == Phase::Halted
            || goal.status != "blocked"
            || turn.id == self.last_turn
            || !turn.retryable(goal, now)
        {
            return false;
        }
        if self.attempt > 0 && goal.tokens_used > self.baseline {
            self.wasted += 1;
        }
        self.last_turn.clone_from(&turn.id);
        self.error_time = turn.completed_at.unwrap();
        self.baseline = goal.tokens_used;
        if self.wasted >= 5 {
            self.phase = Phase::Halted;
            return false;
        }
        self.due = now + DELAYS[self.attempt.min(DELAYS.len() - 1)];
        self.attempt = self.attempt.saturating_add(1);
        self.phase = Phase::Waiting;
        true
    }

    pub fn eligible(&self, goal: &Goal, now: u64) -> bool {
        self.phase == Phase::Waiting
            && goal.status == "blocked"
            && now >= self.due
            && now <= self.error_time + 1800
    }

    pub fn complete(&mut self, turn: &Turn) -> bool {
        if !matches!(self.phase, Phase::Sent | Phase::Verifying)
            || turn.id == self.last_turn
            || turn.status != "completed"
        {
            return false;
        }
        self.phase = Phase::Watching;
        self.attempt = 0;
        self.wasted = 0;
        true
    }
}

#[cfg(test)]
mod tests;
