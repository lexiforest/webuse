from webuse.model_metadata import serving_model_limits


def fake_endpoint(monkeypatch, routes):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return routes.get(url, {})

        return Response()

    monkeypatch.setattr("webuse.model_metadata.requests.get", get)
    return calls


def test_ollama_uses_loaded_context(monkeypatch):
    calls = fake_endpoint(
        monkeypatch,
        {
            "http://localhost:11434/api/ps": {
                "models": [
                    {"name": "other", "context_length": 131072},
                    {"name": "qwen3:8b", "context_length": 8192},
                ]
            },
        },
    )
    limits = serving_model_limits("http://localhost:11434/v1", "qwen3:8b", "secret")
    assert limits["contextWindow"] == 8192
    assert limits["source"] == "Ollama loaded context"
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False
    assert "secret" not in str(limits)


def test_lm_studio_instances_and_native_maximum(monkeypatch):
    fake_endpoint(
        monkeypatch,
        {
            "http://server/proxy/api/v1/models": {
                "models": [
                    {
                        "key": "qwen",
                        "max_context_length": 262144,
                        "loaded_instances": [
                            {"id": "a", "config": {"context_length": 8192}},
                            {"id": "b", "config": {"context_length": 16384}},
                        ],
                    },
                    {
                        "key": "unloaded",
                        "max_context_length": 131072,
                        "loaded_instances": [],
                    },
                ]
            },
        },
    )
    base = "http://server/proxy/v1"
    assert (
        serving_model_limits(base, "qwen", provider="lmstudio")["contextWindow"] == 8192
    )
    assert (
        serving_model_limits(base, "b", provider="lmstudio")["contextWindow"] == 16384
    )
    assert "contextWindow" not in serving_model_limits(
        base, "unloaded", provider="lmstudio"
    )


def test_gateway_metadata_exact_model_and_malformed_values(monkeypatch):
    fake_endpoint(
        monkeypatch,
        {
            "https://gateway/v1/models": {
                "data": [
                    {"id": "other", "max_model_len": 1000000},
                    {"id": "chosen", "max_model_len": 32768, "max_output_tokens": 4096},
                    {"id": "invalid", "context_length": True, "max_output_tokens": -1},
                ]
            },
        },
    )
    limits = serving_model_limits("https://gateway/v1", "chosen")
    assert limits["contextWindow"] == 32768
    assert limits["maxOutputTokens"] == 4096
    assert serving_model_limits("https://gateway/v1", "unknown") == {"local": False}
    assert (
        serving_model_limits("https://gateway/v1", "invalid")["contextWindow"] is None
    )


def test_local_vllm_allocation(monkeypatch):
    fake_endpoint(
        monkeypatch,
        {
            "http://127.0.0.1:8000/v1/models": {
                "data": [
                    {"id": "qwen", "max_model_len": 16384, "context_length": 262144},
                ]
            },
        },
    )
    assert (
        serving_model_limits("http://127.0.0.1:8000/v1", "qwen")["contextWindow"]
        == 16384
    )


def test_missing_metadata_is_not_unlimited(monkeypatch):
    def failed(*args, **kwargs):
        raise TimeoutError("server unavailable")

    monkeypatch.setattr("webuse.model_metadata.requests.get", failed)
    assert serving_model_limits("http://127.0.0.1:1234/v1", "unknown") == {
        "local": True
    }
