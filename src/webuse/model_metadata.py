"""Read serving limits for Harness without loading a model or doing inference."""

from urllib.parse import urlsplit, urlunsplit

from curl_cffi import requests


def _positive(value):
    return value if type(value) is int and value > 0 else None


def serving_model_limits(base_url, model, api_key="", *, provider="", timeout=1):
    """Prefer loaded allocations; native model maxima aren't serving limits."""
    url = urlsplit(base_url)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    local = (
        provider in {"ollama", "lmstudio"}
        or url.port in {1234, 11434}
        or url.hostname
        in {
            "localhost",
            "127.0.0.1",
            "::1",
            "host.docker.internal",
        }
    )
    result = {"local": local}

    def get(path):
        try:
            response = requests.get(
                path, headers=headers, timeout=timeout, allow_redirects=False
            )
            response.raise_for_status()
            value = response.json()
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    # Native APIs share the configured origin and optional reverse-proxy prefix.
    root_path = url.path.rstrip("/").removesuffix("/v1")
    root = urlunsplit((url.scheme, url.netloc, root_path, "", ""))
    if local:
        running = get(f"{root}/api/ps").get("models", [])
        for entry in running if isinstance(running, list) else []:
            if not isinstance(entry, dict):
                continue
            if model in (entry.get("name"), entry.get("model")):
                context = _positive(entry.get("context_length"))
                if context:
                    return {
                        **result,
                        "contextWindow": context,
                        "source": "Ollama loaded context",
                    }
        models = get(f"{root}/api/v1/models").get("models", [])
        for entry in models if isinstance(models, list) else []:
            if not isinstance(entry, dict):
                continue
            instances = entry.get("loaded_instances", [])
            contexts = []
            for instance in instances if isinstance(instances, list) else []:
                if not isinstance(instance, dict):
                    continue
                if model not in (entry.get("key"), instance.get("id")):
                    continue
                config = instance.get("config") or {}
                context = (
                    _positive(config.get("context_length"))
                    if isinstance(config, dict)
                    else None
                )
                if context:
                    contexts.append(context)
            if contexts:
                # A model key may route to several loaded instances.
                return {
                    **result,
                    "contextWindow": min(contexts),
                    "source": "LM Studio loaded context",
                }
    models = get(f"{base_url.rstrip('/')}/models").get("data", [])
    for entry in models if isinstance(models, list) else []:
        if not isinstance(entry, dict) or entry.get("id") != model:
            continue
        # Common serving metadata (vLLM, OpenRouter, compatible gateways).
        context = next(
            (
                value
                # vLLM max_model_len is a serving allocation. Other local
                # /models fields may only describe the trained/native maximum.
                for key in (
                    ("max_model_len",)
                    if local
                    else ("max_model_len", "context_length", "context_window")
                )
                if (value := _positive(entry.get(key)))
            ),
            None,
        )
        output = _positive(entry.get("max_output_tokens"))
        return {
            **result,
            "contextWindow": context,
            "maxOutputTokens": output,
            "source": "endpoint",
        }
    return result
