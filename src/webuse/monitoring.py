"""Harness monitoring config and Prometheus HTTP transport (JSON over stdin)."""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from curl_cffi import requests

from .config import load_webuse_config


def connection():
    try:
        env = os.environ.get("WEBUSE_PROMETHEUS_URL", "")
        if env:
            return {"prometheusUrl": env, "source": "environment"}
        config = load_webuse_config(
            directory=Path(os.environ.get("WEBUSE_CONFIG_DIR") or os.getcwd())
        )
        monitoring = config.get("monitoring") or {}
        return {
            "prometheusUrl": monitoring.get("prometheus_url", ""),
            "source": "configuration",
        }
    except Exception:
        return {
            "prometheusUrl": "",
            "source": "configuration",
            "error": "Cannot read monitoring configuration. Check .webuserc.yaml.",
        }


def query(base, spec):
    try:
        url = urlsplit(base)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
        ):
            raise ValueError("Invalid endpoint")
        endpoint = "query_range" if "start" in spec else "query"
        params = {
            key: value
            for key, value in spec.items()
            if key in {"query", "start", "end", "step", "time"}
        }
        params.update(timeout="5s", limit=50)
        response = requests.get(
            f"{base.rstrip('/')}/api/v1/{endpoint}",
            params=params,
            timeout=7,
            allow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "success":
            return {"error": "Prometheus could not evaluate this query."}
        return {"data": data.get("data"), "warnings": data.get("warnings", [])}
    except Exception:
        return {
            "error": "Cannot query Prometheus. Check the endpoint and server connection."
        }


def main():
    value = json.load(sys.stdin)
    if value.get("action") == "config":
        result = connection()
    else:
        specs = value.get("queries", [])[:12]
        with ThreadPoolExecutor(max_workers=6) as pool:
            result = list(pool.map(lambda spec: query(value["url"], spec), specs))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
