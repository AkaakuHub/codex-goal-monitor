use super::*;
use serde_json::json;

fn goal() -> Goal {
    Goal {
        status: "blocked".into(),
        created_at: 90,
        objective: "Finish the task".into(),
        tokens_used: 100,
    }
}

fn failed(id: &str) -> Turn {
    serde_json::from_value(
        json!({"id": id, "status": "failed", "startedAt": 100, "completedAt": 100,
        "error": {"message": "", "codexErrorInfo": "serverOverloaded"}}),
    )
    .unwrap()
}

#[test]
fn only_capacity_and_stream_errors_are_retryable() {
    for info in [
        json!("serverOverloaded"),
        json!("rateLimitExceeded"),
        json!({"httpConnectionFailed": {"httpStatusCode": 429}}),
        json!({"responseStreamDisconnected": {"httpStatusCode": 500}}),
    ] {
        let mut turn = failed("error");
        turn.error = Some(json!({"message": "", "codexErrorInfo": info}));
        assert!(turn.retryable(&goal(), 110));
    }
    for info in [
        "other",
        "usageLimitExceeded",
        "unauthorized",
        "contextWindowExceeded",
    ] {
        let mut turn = failed("error");
        turn.error = Some(json!({"codexErrorInfo": info}));
        assert!(!turn.retryable(&goal(), 110));
    }
    for status in ["inProgress", "interrupted", "completed"] {
        let mut turn = failed("error");
        turn.status = status.into();
        assert!(!turn.retryable(&goal(), 110));
    }
}

#[test]
fn remote_compaction_stream_error_is_retryable() {
    let mut turn = failed("error");
    turn.error = Some(
        json!({"message": "Error running remote compact task: stream disconnected before completion: connection reset"}),
    );
    assert!(turn.retryable(&goal(), 110));
}

#[test]
fn a_long_turn_uses_its_completion_time_for_error_age() {
    let mut turn = failed("long");
    turn.completed_at = Some(4000);
    assert!(turn.retryable(&goal(), 4001));
    assert!(!turn.retryable(&goal(), 5801));
}

#[test]
fn stale_future_and_previous_goal_errors_are_rejected() {
    let mut turn = failed("error");
    for started in [89, 111] {
        turn.started_at = Some(started);
        assert!(!turn.retryable(&goal(), 110));
    }
    assert!(!failed("error").retryable(&goal(), 1901));
}

#[test]
fn retries_back_off_and_deduplicate_failed_turns() {
    let mut recovery = Recovery::default();
    for (index, delay) in [30, 60, 120, 300, 600, 600].iter().enumerate() {
        let turn = failed(&index.to_string());
        assert!(recovery.schedule(&turn, &goal(), 110));
        assert_eq!(recovery.due, 110 + delay);
        assert!(!recovery.schedule(&turn, &goal(), 110));
        assert_eq!(recovery.attempt, index + 1);
    }
}

#[test]
fn paused_complete_and_limited_goals_are_never_resumed() {
    let mut recovery = Recovery::default();
    recovery.schedule(&failed("error"), &goal(), 110);
    assert!(!recovery.eligible(&goal(), 139));
    assert!(recovery.eligible(&goal(), 140));
    assert!(!recovery.eligible(&goal(), 1911));
    for status in [
        "active",
        "paused",
        "complete",
        "usageLimited",
        "budgetLimited",
    ] {
        let goal = Goal {
            status: status.into(),
            ..goal()
        };
        assert!(!recovery.eligible(&goal, 140));
        assert!(!Recovery::default().schedule(&failed("error"), &goal, 110));
    }
}

#[test]
fn capacity_without_token_consumption_keeps_retrying() {
    let mut recovery = Recovery::default();
    for index in 0..20 {
        assert!(recovery.schedule(&failed(&index.to_string()), &goal(), 110));
    }
    assert_eq!(recovery.wasted, 0);
}

#[test]
fn five_token_consuming_failed_resumes_stop() {
    let mut recovery = Recovery::default();
    assert!(recovery.schedule(&failed("initial"), &goal(), 110));
    for index in 1..=5 {
        let goal = Goal {
            tokens_used: 100 + index,
            ..goal()
        };
        assert_eq!(
            recovery.schedule(&failed(&index.to_string()), &goal, 110),
            index < 5
        );
    }
    assert_eq!(recovery.phase, Phase::Halted);
}

#[test]
fn only_a_new_completed_turn_confirms_recovery() {
    let mut recovery = Recovery {
        phase: Phase::Verifying,
        last_turn: "failed".into(),
        attempt: 3,
        wasted: 2,
        ..Recovery::default()
    };
    for status in ["inProgress", "interrupted", "failed"] {
        let mut turn = failed("new");
        turn.status = status.into();
        assert!(!recovery.complete(&turn));
    }
    let mut turn = failed("failed");
    turn.status = "completed".into();
    assert!(!recovery.complete(&turn));
    turn.id = "new".into();
    assert!(recovery.complete(&turn));
    assert_eq!(
        (recovery.attempt, recovery.wasted, recovery.phase),
        (0, 0, Phase::Watching)
    );
}
