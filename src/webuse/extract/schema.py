"""Validate declarative extraction before crawling."""

from collections.abc import Callable
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError, model_validator

from ..exceptions import ConfigError


class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_min_length=1)

    css: str | None = None
    css_find: str | None = None
    llm_extract: str | None = None
    llm_find: str | None = None
    attr: str | None = None
    all: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_selector(cls, value: Any) -> Any:
        return {"css": value} if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        operations = ("css", "css_find", "llm_extract", "llm_find")
        selected = [key for key in operations if key in self.model_fields_set]
        if len(selected) != 1 or getattr(self, selected[0]) is None:
            raise ValueError(
                "specify exactly one of css, css_find, llm_extract, or llm_find"
            )
        if selected[0] == "llm_extract" and "attr" in self.model_fields_set:
            raise ValueError("llm_extract extracts values; use llm_find for attr")
        if selected[0] in {"css_find", "llm_find"} and "all" in self.model_fields_set:
            raise ValueError(
                f"{selected[0]} selects one element and does not support all"
            )
        return self


class ItemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_min_length=1)

    fields: dict[str, FieldRule]
    item_css: str | None = None
    item_model: str | type[BaseModel] | None = None
    type: str | None = None


class ExtractionRules(RootModel[dict[str, dict[str, ItemSpec]]]):
    """Request category -> item name -> specification with required fields."""

    model_config = ConfigDict(strict=True)


def compile_extraction(
    extract: Any,
) -> ExtractionRules | Callable[..., Any] | None:
    if extract is None or callable(extract) or isinstance(extract, ExtractionRules):
        return extract
    try:
        return ExtractionRules.model_validate(extract)
    except ValidationError as exc:
        raise ConfigError(f"Invalid extraction rules: {exc}") from exc
