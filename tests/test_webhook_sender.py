import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from whatsapp_bot_system.executor import WebhookSender


class _Handler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get('content-length', '0'))
        payload = self.rfile.read(length).decode()
        self.__class__.received.append(json.loads(payload))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'outbound_message_id': 'webhook-msg-001'}).encode())

    def log_message(self, format, *args):
        return


def test_webhook_sender_posts_payload_and_returns_message_id():
    server = HTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f'http://127.0.0.1:{server.server_port}/send'
        sender = WebhookSender(endpoint=endpoint)

        outbound_id = sender.send(
            candidate_id='cand_001',
            text='Welcome to Moms Club!',
            context={'group_id': '120363001234567890@g.us'},
        )

        assert outbound_id == 'webhook-msg-001'
        assert _Handler.received[-1]['candidate_id'] == 'cand_001'
        assert _Handler.received[-1]['text'] == 'Welcome to Moms Club!'
    finally:
        server.shutdown()
        server.server_close()
