import asyncio
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class Notifications:
    def __init__(self, url: str):
        self.url = url
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)

    def send(self, text: str) -> None:
        try:
            self.queue.put_nowait(text[:1900])
        except asyncio.QueueFull:
            logger.error('Discord通知キューが満杯です')

    def post(self, text: str) -> float:
        request = urllib.request.Request(self.url, data=json.dumps({'content': text, 'allowed_mentions': {'parse': []}}).encode(), headers={'Content-Type': 'application/json', 'User-Agent': 'CodexGoalMonitor/1.0'})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                logger.info('Discord通知成功 HTTP %s', response.status)
            return 0
        except urllib.error.HTTPError as error:
            logger.warning('Discord通知失敗 HTTP %s', error.code)
            if error.code == 429:
                try:
                    return min(60, max(1, float(json.loads(error.read()).get('retry_after', 5))))
                except (ValueError, TypeError):
                    return 5
            return 5
        except (OSError, ValueError):
            logger.warning('Discord接続に失敗しました')
            return 5

    async def run(self) -> None:
        while True:
            text = await self.queue.get()
            for _ in range(5):
                delay = await asyncio.to_thread(self.post, text)
                if not delay:
                    break
                await asyncio.sleep(delay)
            self.queue.task_done()
