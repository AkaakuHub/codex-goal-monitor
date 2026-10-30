use std::sync::mpsc;

use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};
use tokio::task::JoinHandle;
use tokio_tungstenite::tungstenite::Message;
use uds_compat::UnixStream;

use super::*;
use crate::{config::Settings, monitor::client::Client, notifications::Notification};

async fn session(
    responses: Vec<(&'static str, Value)>,
) -> (Session, mpsc::Receiver<Notification>, JoinHandle<()>) {
    let (client, server) = UnixStream::pair().unwrap();
    let server = tokio::spawn(async move {
        let mut socket = tokio_tungstenite::accept_async(server).await.unwrap();
        for (method, result) in std::iter::once(("initialize", json!({}))).chain(responses) {
            let message = loop {
                let Message::Text(text) = socket.next().await.unwrap().unwrap() else {
                    continue;
                };
                let message: Value = serde_json::from_str(&text).unwrap();
                if message["method"] != "initialized" {
                    break message;
                }
            };
            assert_eq!(message["method"], method);
            if method == "turn/start" {
                assert_eq!(
                    message["params"]["input"],
                    json!([{"type": "text", "text": "continue"}])
                );
            }
            socket
                .send(Message::Text(
                    json!({"id": message["id"], "result": result})
                        .to_string()
                        .into(),
                ))
                .await
                .unwrap();
        }
    });
    let client = Client::from_stream(client).await.unwrap();
    let (sender, receiver) = mpsc::sync_channel(10);
    (
        Session::new(client, Settings::default(), sender),
        receiver,
        server,
    )
}

fn turn(status: &str, error: Value) -> Value {
    json!({"data": [{
        "id": if status == "failed" { "failed" } else { "new" },
        "status": status,
        "startedAt": now() - 10,
        "completedAt": now() - 1,
        "error": error
    }]})
}

#[tokio::test]
async fn global_status_events_recover_capacity_and_stream_errors_without_a_goal() {
    for error in [
        json!({"codexErrorInfo": "serverOverloaded"}),
        json!({"codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": 500}}}),
    ] {
        let failed = turn("failed", error);
        let (mut session, notifications, server) = session(vec![
            ("thread/goal/get", json!({"goal": null})),
            ("thread/turns/list", failed.clone()),
            (
                "thread/read",
                json!({"thread": {"status": {"type": "idle"}}}),
            ),
            ("thread/goal/get", json!({"goal": null})),
            ("thread/turns/list", failed),
            ("thread/resume", json!({})),
            (
                "turn/start",
                json!({"turn": {"id": "new", "status": "inProgress"}}),
            ),
            ("thread/turns/list", turn("completed", Value::Null)),
        ])
        .await;
        session
            .event(json!({"method": "thread/status/changed", "params": {
                "threadId": "thread", "status": {"type": "systemError"}
            }}))
            .await
            .unwrap();
        session.inspect("thread").await.unwrap();
        assert_eq!(
            notifications.try_recv().unwrap().title,
            "Codex Recovery Scheduled"
        );
        session.targets.get_mut("thread").unwrap().recovery.due = now();
        session.resume("thread").await.unwrap();
        assert_eq!(
            notifications.try_recv().unwrap().title,
            "Codex Resume Started"
        );
        session.inspect("thread").await.unwrap();
        assert_eq!(notifications.try_recv().unwrap().title, "Codex Resumed");
        assert_eq!(session.targets["thread"].recovery.phase, Phase::Watching);
        server.await.unwrap();
    }
}

#[tokio::test]
async fn a_manual_stop_during_the_wait_cancels_recovery() {
    let failed = turn("failed", json!({"codexErrorInfo": "serverOverloaded"}));
    let (mut session, notifications, server) = session(vec![
        ("thread/goal/get", json!({"goal": null})),
        ("thread/turns/list", failed),
        (
            "thread/read",
            json!({"thread": {"status": {"type": "idle"}}}),
        ),
        ("thread/goal/get", json!({"goal": null})),
        ("thread/turns/list", turn("interrupted", Value::Null)),
    ])
    .await;
    session.snapshot("thread").await.unwrap();
    session.inspect("thread").await.unwrap();
    notifications.try_recv().unwrap();
    session.targets.get_mut("thread").unwrap().recovery.due = now();
    session.resume("thread").await.unwrap();
    assert_eq!(session.targets["thread"].recovery.phase, Phase::Watching);
    assert!(notifications.try_recv().is_err());
    server.await.unwrap();
}

#[tokio::test]
async fn running_threads_are_not_resumed() {
    let failed = turn("failed", json!({"codexErrorInfo": "serverOverloaded"}));
    let (mut session, notifications, server) = session(vec![
        ("thread/goal/get", json!({"goal": null})),
        ("thread/turns/list", failed),
        (
            "thread/read",
            json!({"thread": {"status": {"type": "active"}}}),
        ),
    ])
    .await;
    session.snapshot("thread").await.unwrap();
    session.inspect("thread").await.unwrap();
    notifications.try_recv().unwrap();
    session.targets.get_mut("thread").unwrap().recovery.due = now();
    session.resume("thread").await.unwrap();
    assert!(notifications.try_recv().is_err());
    server.await.unwrap();
}

#[tokio::test]
async fn blocked_goals_still_resume_through_the_goal_api() {
    let failed = turn("failed", json!({"codexErrorInfo": "serverOverloaded"}));
    let mut goal = json!({"status": "blocked", "createdAt": now() - 60,
        "objective": "Finish", "tokensUsed": 100});
    let mut active = goal.clone();
    active["status"] = json!("active");
    let (mut session, notifications, server) = session(vec![
        ("thread/goal/get", json!({"goal": goal})),
        ("thread/turns/list", failed.clone()),
        (
            "thread/read",
            json!({"thread": {"status": {"type": "idle"}}}),
        ),
        ("thread/goal/get", json!({"goal": goal})),
        ("thread/turns/list", failed),
        ("thread/goal/set", json!({"goal": active})),
        ("thread/turns/list", turn("completed", Value::Null)),
    ])
    .await;
    session.snapshot("thread").await.unwrap();
    session.inspect("thread").await.unwrap();
    assert_eq!(
        notifications.try_recv().unwrap().title,
        "Codex Recovery Scheduled"
    );
    session.targets.get_mut("thread").unwrap().recovery.due = now();
    session.resume("thread").await.unwrap();
    assert_eq!(
        notifications.try_recv().unwrap().title,
        "Codex Goal Resume Started"
    );
    session.inspect("thread").await.unwrap();
    assert_eq!(notifications.try_recv().unwrap().title, "Codex Resumed");
    goal["status"] = json!("paused");
    session.goal("thread", serde_json::from_value(goal).unwrap(), None, false);
    assert!(
        !session.targets["thread"]
            .recovery
            .eligible(session.targets["thread"].goal.as_ref(), now())
    );
    server.await.unwrap();
}
