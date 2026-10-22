use super::*;

#[tokio::test]
async fn notifications_are_preserved_while_waiting_for_a_response() {
    let (client, server) = UnixStream::pair().unwrap();
    let server = tokio::spawn(async move {
        let mut socket = tokio_tungstenite::accept_async(server).await.unwrap();
        while let Some(Ok(Message::Text(text))) = socket.next().await {
            let message: Value = serde_json::from_str(&text).unwrap();
            if message["method"] == "initialized" {
                continue;
            }
            if message["method"] == "thread/goal/get" {
                socket.send(Message::Text(json!({"method": "thread/goal/updated", "params": {"threadId": "thread", "goal": {"status": "paused"}}}).to_string().into())).await.unwrap();
            }
            socket
                .send(Message::Text(
                    json!({"id": message["id"], "result": {"goal": null}})
                        .to_string()
                        .into(),
                ))
                .await
                .unwrap();
        }
    });
    let mut client = Client::from_stream(client).await.unwrap();
    let result = client
        .request("thread/goal/get", json!({"threadId": "thread"}))
        .await
        .unwrap();
    assert!(result["goal"].is_null());
    let event = client.next().await.unwrap();
    assert_eq!(event["params"]["goal"]["status"], "paused");
    server.abort();
}

#[tokio::test]
async fn a_rejected_request_is_not_reported_as_success() {
    let (client, server) = UnixStream::pair().unwrap();
    let server = tokio::spawn(async move {
        let mut socket = tokio_tungstenite::accept_async(server).await.unwrap();
        while let Some(Ok(Message::Text(text))) = socket.next().await {
            let message: Value = serde_json::from_str(&text).unwrap();
            if message["method"] == "initialized" {
                continue;
            }
            let result = if message["method"] == "initialize" {
                json!({"id": message["id"], "result": {}})
            } else {
                json!({"id": message["id"], "error": {"code": -32600, "message": "rejected"}})
            };
            socket
                .send(Message::Text(result.to_string().into()))
                .await
                .unwrap();
        }
    });
    let mut client = Client::from_stream(client).await.unwrap();
    assert!(
        client
            .request(
                "thread/goal/set",
                json!({"threadId": "thread", "status": "active"})
            )
            .await
            .is_err()
    );
    server.abort();
}
