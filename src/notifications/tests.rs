use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpListener,
    sync::{Arc, mpsc},
    time::Duration,
};

use serde_json::Value;

use super::*;

#[test]
fn a_rate_limited_webhook_is_retried_with_the_sender_label_and_mentions_disabled() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let (result, received) = mpsc::channel();
    std::thread::spawn(move || {
        let mut payloads = Vec::new();
        for attempt in 0..2 {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut reader = BufReader::new(&mut stream);
            let mut length = 0;
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                if line == "\r\n" {
                    break;
                }
                if let Some(value) = line.to_ascii_lowercase().strip_prefix("content-length:") {
                    length = value.trim().parse().unwrap();
                }
            }
            let mut body = vec![0; length];
            reader.read_exact(&mut body).unwrap();
            payloads.push(serde_json::from_slice::<Value>(&body).unwrap());
            let response = if attempt == 0 {
                "HTTP/1.1 429 Too Many Requests\r\nContent-Type: application/json\r\nContent-Length: 17\r\nConnection: close\r\n\r\n{\"retry_after\":0}"
            } else {
                "HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n"
            };
            stream.write_all(response.as_bytes()).unwrap();
        }
        result.send(payloads).unwrap();
    });
    let sender = start(Arc::new(|_| {}));
    sender
        .send(Notification {
            settings: Settings {
                webhook_url: format!("http://{address}/webhook"),
                sender_label: "開発PC".into(),
                autostart: false,
            },
            thread: "test-thread".into(),
            title: "Codex Goal Completed",
            detail: "Goalが完了しました。",
        })
        .unwrap();
    let payloads = received.recv_timeout(Duration::from_secs(8)).unwrap();
    assert_eq!(payloads.len(), 2);
    assert_eq!(payloads[0], payloads[1]);
    assert_eq!(payloads[0]["username"], "開発PC");
    assert_eq!(
        payloads[0]["allowed_mentions"]["parse"],
        serde_json::json!([])
    );
    assert!(
        payloads[0]["content"]
            .as_str()
            .unwrap()
            .contains("Source: 開発PC\nThread: test-thread")
    );
}
