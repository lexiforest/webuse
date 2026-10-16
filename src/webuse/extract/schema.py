"""Validate declarative selection and structured extraction before crawling."""

from collections.abc import Callable
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    RootModel,
    ValidationError,
    model_validator,
)

from ..exceptions import ConfigError
from ..selection import SelectionRule
from .structured import OutputSchema


class SelectedField(SelectionRule):
    attr: str | None = None
    required: bool = False


class StructuredValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_min_length=1)

    llm_extract: str
    output_schema: Any = Field(alias="schema")
    _output: OutputSchema = PrivateAttr()

    @model_validator(mode="after")
    def compile_schema(self) -> Self:
        try:
            self._output = OutputSchema(self.output_schema)
        except Exception as exc:
            raise ValueError(f"Invalid extraction schema: {exc}") from exc
        return self


FieldRule = Annotated[
    SelectedField | StructuredValue,
    BeforeValidator(lambda value: {"css": value} if isinstance(value, str) else value),
]


class ItemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_min_length=1)

    fields: dict[str, FieldRule] | None = None
    llm_extract: str | None = None
    output_schema: Any = Field(default=None, alias="schema")
    item_css: str | None = None
    item_model: str | type[BaseModel] | None = None
    type: str | None = None
    _output: OutputSchema | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        if (self.fields is None) == (self.llm_extract is None):
            raise ValueError("specify exactly one of fields or llm_extract")
        if self.llm_extract is not None:
            if self.output_schema is None:
                raise ValueError("llm_extract requires schema")
            try:
                self._output = OutputSchema(self.output_schema)
            except Exception as exc:
                raise ValueError(f"Invalid extraction schema: {exc}") from exc
        elif "output_schema" in self.model_fields_set:
            raise ValueError("schema is only valid with llm_extract")
        return self


class ExtractionRules(RootModel[dict[str, dict[str, ItemSpec]]]):
    """Request page_type -> named record -> fields or structured extraction."""

    model_config = ConfigDict(strict=True)


def compile_extraction(extract: Any) -> ExtractionRules | Callable[..., Any] | None:
    if extract is None or callable(extract) or isinstance(extract, ExtractionRules):
        return extract
    try:
        return ExtractionRules.model_validate(extract)
    except ValidationError as exc:
        raise ConfigError(f"Invalid extraction rules: {exc}") from exc
