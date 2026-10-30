use std::{collections::VecDeque, path::Path, time::Duration};

use anyhow::{Context, Result, bail};
use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};
use tokio_tungstenite::{
    WebSocketStream,
    tungstenite::{Message, protocol::WebSocketConfig},
};
use uds_compat::UnixStream;

#[derive(Debug)]
pub struct RejectedRequest;

impl std::fmt::Display for RejectedRequest {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("Codexが要求を拒否しました。")
    }
}

impl std::error::Error for RejectedRequest {}

pub struct Client {
    socket: WebSocketStream<UnixStream>,
    sequence: u64,
    events: VecDeque<Value>,
}

impl Client {
    pub async fn connect(path: &Path) -> Result<Self> {
        #[cfg(unix)]
        let resolved = path.canonicalize()?;
        #[cfg(unix)]
        let path = resolved.as_path();
        let socket = UnixStream::connect(path).await?;
        Self::from_stream(socket).await
    }

    pub(super) async fn from_stream(socket: UnixStream) -> Result<Self> {
        let (socket, _) = tokio::time::timeout(
            Duration::from_secs(10),
            tokio_tungstenite::client_async_with_config(
                "ws://localhost/",
                socket,
                Some(WebSocketConfig::default().max_message_size(Some(1024 * 1024))),
            ),
        )
        .await??;
        let mut client = Self {
            socket,
            sequence: 0,
            events: VecDeque::new(),
        };
        client.request("initialize", json!({
            "clientInfo": {"name": "codex-goal-monitor", "version": env!("CARGO_PKG_VERSION")},
            "capabilities": {"experimentalApi": true}
        })).await?;
        client.send(json!({"method": "initialized"})).await?;
        Ok(client)
    }

    async fn send(&mut self, value: Value) -> Result<()> {
        self.socket
            .send(Message::Text(value.to_string().into()))
            .await?;
        Ok(())
    }

    async fn read(&mut self) -> Result<Value> {
        loop {
            match self
                .socket
                .next()
                .await
                .context("Codexとの接続が閉じられました。")??
            {
                Message::Text(text) => {
                    return serde_json::from_str(&text).context("Codexの応答形式が不正です。");
                }
                Message::Close(_) => bail!("Codexとの接続が閉じられました。"),
                Message::Ping(_) => self.socket.flush().await?,
                _ => {}
            }
        }
    }

    pub async fn request(&mut self, method: &str, params: Value) -> Result<Value> {
        self.sequence += 1;
        let identifier = self.sequence;
        self.send(json!({"id": identifier, "method": method, "params": params}))
            .await?;
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                let message = self.read().await?;
                if message["id"].as_u64() == Some(identifier) {
                    if message.get("error").is_some() {
                        return Err(RejectedRequest.into());
                    }
                    return Ok(message["result"].clone());
                }
                if message.get("method").is_some() && message.get("id").is_none() {
                    if self.events.len() >= 256 {
                        bail!("Codexのイベント待機件数が上限に達しました。");
                    }
                    self.events.push_back(message);
                }
            }
        })
        .await
        .context("Codexからの応答がありません。")?
    }

    pub async fn next(&mut self) -> Result<Value> {
        match self.events.pop_front() {
            Some(event) => Ok(event),
            None => self.read().await,
        }
    }
}

#[cfg(all(test, unix))]
mod tests;
