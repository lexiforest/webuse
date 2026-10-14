"""HTML parsing, declarative extraction, LLM value extraction, and element lookup."""

from .parser import Document, Element
from .rules import (
    ParseResult,
    aextract_response,
    extract_handles_category,
    extract_items,
    extract_response,
    normalize_parse_result,
)
from .smart import (
    SMART_EXTRACTION_SYSTEM_PROMPT,
    SMART_FIRST_EXTRACTION_SYSTEM_PROMPT,
    coerce_smart_output,
    extract_smart,
)
from .resolver import LlmSmartResolver, resolve_element

__all__ = [
    "Document",
    "Element",
    "ParseResult",
    "aextract_response",
    "extract_handles_category",
    "extract_items",
    "extract_response",
    "normalize_parse_result",
    "LlmSmartResolver",
    "SMART_EXTRACTION_SYSTEM_PROMPT",
    "SMART_FIRST_EXTRACTION_SYSTEM_PROMPT",
    "coerce_smart_output",
    "extract_smart",
    "resolve_element",
]
