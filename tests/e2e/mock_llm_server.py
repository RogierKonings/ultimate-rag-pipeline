"""
Minimal mock LLM server for E2E tests.

Implements the OpenAI-compatible /v1/chat/completions endpoint
so the orchestrator can function in CI without a real LLM.
"""

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler


class MockLLMHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if "/v1/models" in self.path:
            self._handle_models()
        else:
            # Health check / catch-all
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

    def _handle_models(self):
        response = {
            "object": "list",
            "data": [{"id": "mock-llm", "object": "model", "owned_by": "mock"}],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def do_POST(self):
        if "/v1/chat/completions" in self.path:
            self._handle_chat_completion()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_chat_completion(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        request = json.loads(body) if body else {}

        model = request.get("model", "mock-llm")
        messages = request.get("messages", [])
        stream = request.get("stream", False)

        # Extract the user's query from the last user message
        user_query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_query = msg.get("content", "")
                break

        if stream:
            self._handle_stream(model, user_query)
        else:
            self._handle_non_stream(model, user_query)

    def _handle_non_stream(self, model, user_query):
        answer = self._generate_answer(user_query)
        response = {
            "id": "mock-completion-1",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 30,
                "total_tokens": 80,
            },
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def _handle_stream(self, model, user_query):
        answer = self._generate_answer(user_query)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # Send content in chunks
        words = answer.split()
        for i, word in enumerate(words):
            chunk = {
                "id": "mock-stream-1",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": word + " "},
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        # Send final chunk with finish_reason
        final_chunk = {
            "id": "mock-stream-1",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}
            ],
        }
        self.wfile.write(f"data: {json.dumps(final_chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _generate_answer(self, user_query):
        return (
            "Based on the available information, here is the answer to your question. "
            "Python is a high-level programming language created by Guido van Rossum "
            "in 1991. Machine learning includes supervised, unsupervised, and "
            "reinforcement learning. Cloud computing uses IaaS, PaaS, and SaaS models. "
            "PostgreSQL was first released in 1996. React, Vue, and Angular are popular "
            "frontend frameworks. The OWASP Top 10 lists critical security risks. "
            "Terraform is used for infrastructure as code. REST APIs use GET, POST, "
            "PUT, and DELETE methods. Hash tables provide O(1) average lookup time. "
            "The OSI model has seven layers."
        )

    def log_message(self, format, *args):
        # Suppress per-request logs to keep output clean
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 11434), MockLLMHandler)
    print("Mock LLM server running on port 11434", flush=True)
    server.serve_forever()
