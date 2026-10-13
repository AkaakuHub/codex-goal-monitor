import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Provider(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.webhooks: list[str] = []
        self.requests_count = 0
        self.mode = 'capacity'
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    server: Provider

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"data":[]}')

    def do_POST(self) -> None:
        data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or b'{}')
        if self.path == '/webhook':
            self.server.webhooks.append(data.get('content', ''))
            self.send_response(204)
            self.end_headers()
            return
        self.server.requests_count += 1
        if self.server.mode == 'capacity':
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"server_is_overloaded"}}')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        response = {'id': 'response-test', 'object': 'response', 'status': 'in_progress', 'output': []}
        self.emit('response.created', {'type': 'response.created', 'response': response})
        if self.server.mode == 'stream':
            self.close_connection = True
            return
        time.sleep(4)
        item = {'id': 'message-test', 'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Local test completed.'}]}
        self.emit('response.output_item.done', {'type': 'response.output_item.done', 'output_index': 0, 'item': item})
        response.update(status='completed', output=[item], usage={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2})
        self.emit('response.completed', {'type': 'response.completed', 'response': response})

    def emit(self, kind: str, value: object) -> None:
        try:
            self.wfile.write(f'event: {kind}\ndata: {json.dumps(value)}\n\n'.encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
