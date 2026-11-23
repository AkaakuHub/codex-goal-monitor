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
    pub fn retryable(&self, goal: Option<&Goal>, now: u64) -> bool {
        let (Some(started), Some(completed)) = (self.started_at, self.completed_at) else {
            return false;
        };
        if self.status != "failed"
            || goal.is_some_and(|goal| started < goal.created_at)
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
        let categories = info.as_object();
        if [
            "usageLimitExceeded",
            "unauthorized",
            "contextWindowExceeded",
        ]
        .into_iter()
        .any(|category| {
            info.as_str() == Some(category)
                || categories.is_some_and(|categories| categories.contains_key(category))
        }) {
            return false;
        }
        if let Some(status) = categories.and_then(|categories| {
            categories
                .values()
                .filter_map(|value| value["httpStatusCode"].as_u64())
                .find(|status| (400..600).contains(status))
        }) {
            return retryable_http_status(status);
        }
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
        if categories.is_some_and(|categories| {
            categories.keys().any(|key| {
                matches!(
                    key.as_str(),
                    "responseStreamDisconnected" | "responseStreamConnectionFailed"
                )
            })
        }) {
            return true;
        }
        error["message"].as_str().is_some_and(|message| {
            let compact_error = message
                .strip_prefix("Error running remote compact task:")
                .map(str::trim_start);
            if compact_error
                .unwrap_or(message)
                .starts_with("stream disconnected before completion:")
            {
                return true;
            }
            compact_error.is_some_and(|error| {
                let mut words = error.split_whitespace();
                match (words.next(), words.next(), words.next()) {
                    (Some("unexpected"), Some("status"), Some(status)) => status
                        .trim_end_matches(':')
                        .parse()
                        .is_ok_and(retryable_http_status),
                    _ => false,
                }
            })
        })
    }
}

fn retryable_http_status(status: u64) -> bool {
    matches!(status, 429 | 500 | 502 | 503 | 504)
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
    pub fn schedule(&mut self, turn: &Turn, goal: Option<&Goal>, now: u64) -> bool {
        if self.phase == Phase::Halted
            || goal.is_some_and(|goal| goal.status != "blocked")
            || turn.id == self.last_turn
            || !turn.retryable(goal, now)
        {
            return false;
        }
        let tokens_used = goal.map_or(0, |goal| goal.tokens_used);
        if self.attempt > 0 && tokens_used > self.baseline {
            self.wasted += 1;
        }
        self.last_turn.clone_from(&turn.id);
        self.error_time = turn.completed_at.unwrap();
        self.baseline = tokens_used;
        if self.wasted >= 5 || (goal.is_none() && self.attempt >= 5) {
            self.phase = Phase::Halted;
            return false;
        }
        self.due = now + DELAYS[self.attempt.min(DELAYS.len() - 1)];
        self.attempt = self.attempt.saturating_add(1);
        self.phase = Phase::Waiting;
        true
    }

    pub fn eligible(&self, goal: Option<&Goal>, now: u64) -> bool {
        self.phase == Phase::Waiting
            && goal.is_none_or(|goal| goal.status == "blocked")
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
