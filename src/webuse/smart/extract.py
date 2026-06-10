import json
from typing import Any

from ..llm import create_openai_client, openai_defaults
from ..parser import Document, _text_without_tree


SMART_EXTRACTION_SYSTEM_PROMPT = (
    "Extract data from the provided document text and HTML. Return only one JSON "
    "array containing all matches and no prose. Preserve exact HTML attribute values "
    "when the prompt asks for an "
    "attribute or field such as title, href, src, alt, or aria-label."
)

SMART_FIRST_EXTRACTION_SYSTEM_PROMPT = (
    "Extract data from the provided document text and HTML. Return only the first "
    "matching JSON value and no prose. Preserve exact HTML attribute values when "
    "the prompt asks for an attribute or field such as title, href, src, alt, or "
    "aria-label."
)


def _parse_json_maybe(value: str) -> Any:
    text = value.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def coerce_smart_output(value: str, *, first: bool = False) -> Any:
    parsed = _parse_json_maybe(value)
    if parsed is not value:
        if first:
            return parsed[0] if isinstance(parsed, list) and parsed else parsed
        return parsed if isinstance(parsed, list) else [parsed]
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if first:
        return lines[0] if lines else ""
    return lines if len(lines) > 1 else [value]


def extract_smart(
    document: Document,
    prompt: str,
    *,
    first: bool = False,
    model: str | None = None,
    client: Any = None,
    api_key: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    max_chars: int | None = 12000,
    temperature: float = 0,
    **kwargs: Any,
) -> Any:
    defaults = openai_defaults()
    model = model or defaults.model or "gpt-4.1-mini"
    api_key = api_key or defaults.api_key
    base_url = base_url or defaults.base_url
    html = document.raw_text
    text = _text_without_tree(document.raw_text)
    if max_chars is not None:
        html = html[:max_chars]
        text = text[:max_chars]
    if client is None:
        client = create_openai_client(api_key=api_key, base_url=base_url)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": system_prompt
                or (
                    SMART_FIRST_EXTRACTION_SYSTEM_PROMPT
                    if first
                    else SMART_EXTRACTION_SYSTEM_PROMPT
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Prompt:\n{prompt}\n\n"
                    f"Document text:\n{text}\n\n"
                    f"Document HTML:\n{html}"
                ),
            },
        ],
        temperature=temperature,
        **kwargs,
    )
    return coerce_smart_output(response.choices[0].message.content or "", first=first)
