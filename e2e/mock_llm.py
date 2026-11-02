"""A stand-in OpenAI-compatible AI server (like Ollama or vLLM) for end-to-end tests: no keys, no cost, predictable.

Models: "mock-good" answers like a grounded bot (it quotes the first sentence of the top excerpt and cites it),
"mock-down" always fails with 503, and "mock-broke" says it's out of credit (402), like OpenRouter does.
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def reply_for(body: dict) -> str:
    system = body["messages"][0]["content"]
    everything = json.dumps(body["messages"])
    if "check an assistant's answer" in system:
        return "NONE"
    if "standalone search question" in system:
        return body["messages"][-1]["content"].split("LATEST MESSAGE:")[-1].strip()
    if "suggested questions" in system:
        return "What do you sell?\nDo you ship abroad?\nWhat are your opening hours?"
    if "Reply with the single word OK" in everything:
        return "OK"
    # Answer like a grounded bot: quote the first sentence of the top excerpt and cite it; no excerpt -> not found.
    user = body["messages"][-1]["content"]
    m = re.search(r"\[1\] \(page:[^\n]*\)\n(.+?)(?:\n\n\[\d+\]|\n\nQUESTION:)", user, re.S)
    if not m:
        return "NOT_FOUND"
    first = re.split(r"(?<=[.!?])\s", m.group(1).replace("\n", " ").strip())[0]
    return f"{first.rstrip('.')} [1]."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status: int, body: bytes, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body.get("model")
        if model == "mock-broke":
            return self._send(402, b'{"error":{"message":"This request requires more credits","code":402}}')
        if model == "mock-down":
            return self._send(503, b"overloaded", "text/plain")
        text = reply_for(body)
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        if not body.get("stream"):
            return self._send(200, json.dumps({"choices": [{"message": {"content": text}}], "usage": usage}).encode())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for word in text.split(" "):
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': word + ' '}}]})}\n\n".encode())
        self.wfile.write(f"data: {json.dumps({'choices': [], 'usage': usage})}\n\ndata: [DONE]\n\n".encode())


def start(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    import sys

    start(int(sys.argv[1]) if len(sys.argv) > 1 else 5600)
    threading.Event().wait()
