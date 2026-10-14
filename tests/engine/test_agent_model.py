import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from pydantic import BaseModel

from webuse import AgentLimits, AgentModelError, OpenAISettings, agentic_crawl
from webuse.engine.agent_model import CurlAgentModel


@pytest.fixture
def local_server():
    requests = []
    replies = []
    payloads = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/company")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<h1>Acme</h1>")

        def do_POST(self):
            requests.append((self.path, self.headers.get("Authorization")))
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            payloads.append(payload)
            assert payload["tool_choice"] == "auto"
            assert "max_tokens" not in payload or payload["max_tokens"] > 0
            status, body = replies.pop(0)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, replies, payloads
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def tool_reply(name, **args):
    return (
        200,
        {
            "usage": {"total_tokens": 20},
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "one",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args),
                                },
                            }
                        ],
                    }
                }
            ],
        },
    )


def test_real_curl_model_and_page_sessions_keep_credentials_separate(
    local_server, monkeypatch
):
    from webuse.engine import agentic

    base_url, requests, replies, payloads = local_server
    monkeypatch.setattr(
        agentic,
        "openai_defaults",
        lambda: OpenAISettings(
            model="local",
            api_key="model-secret",
            base_url=f"{base_url}/v1",
        ),
    )
    replies.extend(
        [
            tool_reply("queue_pop"),
            tool_reply(
                "update_record",
                record_id="a",
                fields={"name": "Acme"},
                sources={"name": ["p1"]},
            ),
            tool_reply("emit_record", record_id="a"),
            tool_reply("queue_pop"),
        ]
    )

    class Company(BaseModel):
        name: str

    result = asyncio.run(
        agentic_crawl(
            [f"{base_url}/start"],
            goal="Find company",
            item_model=Company,
            limits=AgentLimits(
                max_requests=5, max_turns=5, max_tokens=100000, max_seconds=5
            ),
            robots_txt=False,
        )
    )
    assert result.close_reason == "finished"
    assert all("max_tokens" not in payload for payload in payloads)
    assert result.items == [Company(name="Acme")]
    assert result.pages[0].css_find("h1").text() == "Acme"
    assert result.stats.queued == 2
    assert [
        (path, auth) for path, auth in requests if path != "/v1/chat/completions"
    ] == [
        ("/start", None),
        ("/company", None),
    ]
    assert all(
        auth == "Bearer model-secret"
        for path, auth in requests
        if path == "/v1/chat/completions"
    )


@pytest.mark.parametrize(
    "status,retryable", [(401, False), (429, True), (503, True), (302, False)]
)
def test_model_http_errors_are_classified_without_response_secrets(
    local_server, status, retryable
):
    base_url, _, replies, _ = local_server
    replies.append((status, {"error": "sensitive provider details"}))

    async def run():
        model = CurlAgentModel(OpenAISettings(model="local", base_url=base_url))
        try:
            with pytest.raises(AgentModelError) as raised:
                await model.complete(messages=[], tools=[], max_tokens=10)
            assert raised.value.retryable == retryable
            assert "sensitive" not in str(raised.value)
        finally:
            await model.close()

    asyncio.run(run())


@pytest.mark.parametrize("cap", [None, 32768])
def test_output_limit_is_sent_only_when_explicit(local_server, cap):
    base_url, _, replies, payloads = local_server
    replies.append(tool_reply("queue_pop"))

    async def run():
        model = CurlAgentModel(OpenAISettings(model="local", base_url=base_url))
        try:
            await model.complete(messages=[], tools=[], max_tokens=cap)
        finally:
            await model.close()

    asyncio.run(run())
    if cap is None:
        assert "max_tokens" not in payloads[0]
    else:
        assert payloads[0]["max_tokens"] == cap


def test_model_response_has_no_hidden_size_or_time_cap(monkeypatch):
    from types import SimpleNamespace

    response = tool_reply("queue_pop")[1]
    response["choices"][0]["message"]["reasoning_content"] = "x" * 1_100_000
    requests = []

    class Session:
        async def post(self, url, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(status_code=200, json=lambda: response)

        async def close(self):
            pass

    monkeypatch.setattr("webuse.engine.agent_model.AsyncSession", Session)

    async def run():
        model = CurlAgentModel(OpenAISettings(model="local"))
        try:
            assert (
                await model.complete(messages=[], tools=[], max_tokens=None) == response
            )
        finally:
            await model.close()

    asyncio.run(run())
    assert requests[0]["timeout"] is None
    assert "content_callback" not in requests[0]
