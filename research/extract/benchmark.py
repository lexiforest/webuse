"""
HTML Extraction Benchmark across LLM Models via OpenRouter.

Three extraction strategies:
  1. Direct extraction — feed HTML, ask model to return structured data.
  2. Selector generation — ask model to produce XPath/CSS selectors, then apply them.
  3. Markdown conversion — ask model to return a clean markdown article.

Usage:
    python benchmark.py                     # run all
    python benchmark.py --strategy direct   # run one strategy
    python benchmark.py --model google/gemini-2.5-flash-preview  # single model
"""

from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from curl_cffi import requests as curl_requests
from lxml import html as lxml_html

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = [
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1",
    "google/gemini-2.5-flash-preview",
    "google/gemini-2.5-pro-preview",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-haiku-4",
]

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"

# ---------------------------------------------------------------------------
# Test cases — each file maps to its expected extractions
# ---------------------------------------------------------------------------

# Every test case lives in DATA_DIR/<key>.html
# ground_truth is strategy-specific:
#   - "direct"   : dict of fields the model should extract
#   - "selector" : dict of field -> expected text (we verify the selector works)
#   - "markdown" : list of strings that MUST appear in the output
TEST_CASES: dict[str, dict[str, Any]] = {
    "hackernews": {
        "description": "Hacker News best stories listing page",
        "direct": {
            "prompt": (
                "Extract the top 5 story titles and their URLs from this "
                "Hacker News page. Return JSON: [{title, url}, ...]"
            ),
            "expected_fields": ["title", "url"],
            "expected_count": 5,
        },
        "selector": {
            "prompt": (
                "Give me a CSS selector that matches every story title link "
                "on this Hacker News page. Return JSON: {css: '...'}"
            ),
            "min_matches": 5,
        },
        "markdown": {
            "prompt": (
                "Convert this Hacker News page into a clean markdown document. "
                "List each story as a markdown link with its title."
            ),
            "must_contain": ["Hacker News"],
        },
    },
    # ---- add more test cases below as you collect pages ----
    # "blog_post": { ... },
    # "product_page": { ... },
    # "table_heavy": { ... },
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    model: str
    strategy: str
    test_case: str
    success: bool
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    raw_output: str = ""
    parsed: Any = None
    error: str = ""
    scores: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# OpenRouter helpers
# ---------------------------------------------------------------------------


def chat(model: str, messages: list[dict], temperature: float = 0) -> dict:
    """Call OpenRouter chat completion and return the full response JSON."""
    assert OPENROUTER_API_KEY, "Set OPENROUTER_API_KEY env var"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/nicegui/webuse",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    resp = curl_requests.post(OPENROUTER_URL, json=body, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()


def extract_content(response: dict) -> str:
    return response["choices"][0]["message"]["content"]


def extract_usage(response: dict) -> tuple[int, int]:
    u = response.get("usage", {})
    return u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def parse_json_from_text(text: str) -> Any:
    """Best-effort JSON parse: strip markdown fences, find first [ or {."""
    text = text.strip()
    # strip ```json ... ```
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    text = text.strip()
    # find first JSON structure
    for i, ch in enumerate(text):
        if ch in ("{", "["):
            # find matching close
            depth = 0
            for j in range(i, len(text)):
                if text[j] in ("{", "["):
                    depth += 1
                elif text[j] in ("}", "]"):
                    depth -= 1
                if depth == 0:
                    return json.loads(text[i : j + 1])
    return json.loads(text)


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


def run_direct(model: str, case_name: str, case_cfg: dict, html: str) -> ExtractionResult:
    """Strategy 1: ask the model to extract structured data directly."""
    cfg = case_cfg["direct"]
    messages = [
        {"role": "system", "content": "You are an expert HTML data extractor. Return ONLY valid JSON."},
        {"role": "user", "content": f"{cfg['prompt']}\n\n<html>\n{html}\n</html>"},
    ]

    t0 = time.monotonic()
    try:
        resp = chat(model, messages)
        latency = time.monotonic() - t0
        content = extract_content(resp)
        inp, out = extract_usage(resp)
        parsed = parse_json_from_text(content)

        # ---- scoring ----
        scores: dict[str, float] = {}
        if isinstance(parsed, list):
            scores["count_match"] = 1.0 if len(parsed) >= cfg.get("expected_count", 1) else len(parsed) / cfg["expected_count"]
            if cfg.get("expected_fields"):
                present = sum(1 for item in parsed for f in cfg["expected_fields"] if f in item)
                total = len(parsed) * len(cfg["expected_fields"])
                scores["field_presence"] = present / total if total else 0
        elif isinstance(parsed, dict) and cfg.get("expected_fields"):
            present = sum(1 for f in cfg["expected_fields"] if f in parsed)
            scores["field_presence"] = present / len(cfg["expected_fields"])

        return ExtractionResult(
            model=model, strategy="direct", test_case=case_name,
            success=True, latency_s=latency,
            input_tokens=inp, output_tokens=out,
            raw_output=content, parsed=parsed, scores=scores,
        )
    except Exception as e:
        return ExtractionResult(
            model=model, strategy="direct", test_case=case_name,
            success=False, latency_s=time.monotonic() - t0,
            error=f"{type(e).__name__}: {e}",
        )


def run_selector(model: str, case_name: str, case_cfg: dict, html: str) -> ExtractionResult:
    """Strategy 2: ask the model to produce a CSS/XPath selector, then apply it."""
    cfg = case_cfg["selector"]
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert at writing CSS and XPath selectors for HTML scraping. "
                "Return ONLY valid JSON with either a 'css' or 'xpath' key."
            ),
        },
        {"role": "user", "content": f"{cfg['prompt']}\n\n<html>\n{html}\n</html>"},
    ]

    t0 = time.monotonic()
    try:
        resp = chat(model, messages)
        latency = time.monotonic() - t0
        content = extract_content(resp)
        inp, out = extract_usage(resp)
        parsed = parse_json_from_text(content)

        # apply selector
        tree = lxml_html.fromstring(html)
        if "css" in parsed:
            from lxml.cssselect import CSSSelector
            sel = CSSSelector(parsed["css"])
            matches = sel(tree)
        elif "xpath" in parsed:
            matches = tree.xpath(parsed["xpath"])
        else:
            matches = []

        n = len(matches)
        min_m = cfg.get("min_matches", 1)
        scores = {
            "selector_valid": 1.0 if n > 0 else 0.0,
            "match_count": min(n / min_m, 1.0) if min_m else 1.0,
        }

        return ExtractionResult(
            model=model, strategy="selector", test_case=case_name,
            success=True, latency_s=latency,
            input_tokens=inp, output_tokens=out,
            raw_output=content,
            parsed={"selector": parsed, "match_count": n},
            scores=scores,
        )
    except Exception as e:
        return ExtractionResult(
            model=model, strategy="selector", test_case=case_name,
            success=False, latency_s=time.monotonic() - t0,
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        )


def run_markdown(model: str, case_name: str, case_cfg: dict, html: str) -> ExtractionResult:
    """Strategy 3: convert HTML to a clean markdown article."""
    cfg = case_cfg["markdown"]
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert at converting web pages to clean, readable Markdown. "
                "Strip navigation, ads, footers — keep only the main content. "
                "Return ONLY the Markdown text."
            ),
        },
        {"role": "user", "content": f"{cfg['prompt']}\n\n<html>\n{html}\n</html>"},
    ]

    t0 = time.monotonic()
    try:
        resp = chat(model, messages)
        latency = time.monotonic() - t0
        content = extract_content(resp)
        inp, out = extract_usage(resp)

        scores: dict[str, float] = {}
        # check must_contain
        if cfg.get("must_contain"):
            hits = sum(1 for s in cfg["must_contain"] if s.lower() in content.lower())
            scores["must_contain"] = hits / len(cfg["must_contain"])
        # basic quality heuristics
        scores["has_markdown_links"] = 1.0 if "](http" in content or "](" in content else 0.0
        scores["length_ratio"] = min(len(content) / (len(html) * 0.1), 1.0)  # expect ~10% of HTML size

        return ExtractionResult(
            model=model, strategy="markdown", test_case=case_name,
            success=True, latency_s=latency,
            input_tokens=inp, output_tokens=out,
            raw_output=content, scores=scores,
        )
    except Exception as e:
        return ExtractionResult(
            model=model, strategy="markdown", test_case=case_name,
            success=False, latency_s=time.monotonic() - t0,
            error=f"{type(e).__name__}: {e}",
        )


STRATEGIES = {
    "direct": run_direct,
    "selector": run_selector,
    "markdown": run_markdown,
}

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def load_html(case_name: str, *, clean: bool = True, target_kb: int = 80) -> str:
    path = DATA_DIR / f"{case_name}.html"
    if not path.exists():
        raise FileNotFoundError(f"Missing test file: {path}")
    raw = path.read_text(encoding="utf-8")
    if clean:
        from clean import clean_html
        cleaned = clean_html(raw, target_kb=target_kb)
        orig_kb = len(raw) / 1024
        clean_kb = len(cleaned) / 1024
        print(f"  Cleaned {orig_kb:,.0f} KB → {clean_kb:,.0f} KB ({(1 - clean_kb/orig_kb)*100:.0f}% reduction)")
        return cleaned
    return raw


def run_benchmark(
    models: list[str] | None = None,
    strategies: list[str] | None = None,
    cases: list[str] | None = None,
) -> list[ExtractionResult]:
    models = models or MODELS
    strategies = strategies or list(STRATEGIES.keys())
    cases = cases or list(TEST_CASES.keys())

    results: list[ExtractionResult] = []

    for case_name in cases:
        case_cfg = TEST_CASES[case_name]
        html = load_html(case_name)
        print(f"\n{'='*60}")
        print(f"Test case: {case_name} — {case_cfg['description']}")
        print(f"HTML size: {len(html):,} chars")
        print(f"{'='*60}")

        for strategy in strategies:
            if strategy not in case_cfg:
                print(f"  [skip] {strategy} — no config for this case")
                continue
            runner = STRATEGIES[strategy]

            for model in models:
                print(f"  [{strategy}] {model} ... ", end="", flush=True)
                result = runner(model, case_name, case_cfg, html)
                results.append(result)

                if result.success:
                    score_str = ", ".join(f"{k}={v:.2f}" for k, v in result.scores.items())
                    print(f"OK  {result.latency_s:.1f}s  tokens={result.input_tokens}+{result.output_tokens}  {score_str}")
                else:
                    print(f"FAIL  {result.error[:80]}")

    return results


def save_results(results: list[ExtractionResult]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"benchmark_{ts}.json"
    data = [asdict(r) for r in results]
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"\nResults saved to {path}")
    return path


def print_summary(results: list[ExtractionResult]) -> None:
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"{'Model':<45} {'Strategy':<12} {'Case':<20} {'OK':<5} {'Time':>6} {'Scores'}")
    print("-" * 120)
    for r in results:
        status = "Y" if r.success else "N"
        score_str = ", ".join(f"{k}={v:.2f}" for k, v in r.scores.items()) if r.scores else r.error[:40]
        print(f"{r.model:<45} {r.strategy:<12} {r.test_case:<20} {status:<5} {r.latency_s:>5.1f}s {score_str}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="HTML extraction benchmark across LLM models")
    parser.add_argument("--model", "-m", action="append", help="Model(s) to test (can repeat)")
    parser.add_argument("--strategy", "-s", action="append", choices=list(STRATEGIES), help="Strategy(ies) to test")
    parser.add_argument("--case", "-c", action="append", help="Test case name(s)")
    parser.add_argument("--no-clean", action="store_true", help="Skip HTML cleaning (send raw HTML)")
    parser.add_argument("--target-kb", type=int, default=80, help="Target size in KB after cleaning (default: 80)")
    parser.add_argument("--list", action="store_true", help="List available test cases and exit")
    args = parser.parse_args()

    if args.list:
        for name, cfg in TEST_CASES.items():
            path = DATA_DIR / f"{name}.html"
            exists = "OK" if path.exists() else "MISSING"
            print(f"  {name:<25} [{exists}]  {cfg['description']}")
        return

    results = run_benchmark(
        models=args.model,
        strategies=args.strategy,
        cases=args.case,
    )
    save_results(results)
    print_summary(results)


if __name__ == "__main__":
    main()
