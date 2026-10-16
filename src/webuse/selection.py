"""Shared declarative element selection for fields and follow rules."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


def validate_selector(css: str | None, llm: str | None) -> None:
    if (css is None) == (llm is None):
        raise ValueError("specify exactly one of css or llm")
    value = css if css is not None else llm
    if not isinstance(value, str) or not value.strip():
        raise ValueError("selector must be a nonempty string")


class SelectionRule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_min_length=1)

    css: str | None = None
    llm: str | None = None
    all: bool = False

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        validate_selector(self.css, self.llm)
        return self

    def select(self, scope):
        if self.css in {".", "&"}:
            return self._current_element(scope)
        if self.all:
            return scope.find_all(css=self.css, llm=self.llm)
        match = scope.find(css=self.css, llm=self.llm)
        return [] if match is None else [match]

    async def aselect(self, scope):
        if self.css in {".", "&"}:
            return self._current_element(scope)
        if self.all:
            return await scope.afind_all(css=self.css, llm=self.llm)
        match = await scope.afind(css=self.css, llm=self.llm)
        return [] if match is None else [match]

    @staticmethod
    def _current_element(scope):
        from .extract.parser import Element

        return [scope] if isinstance(scope, Element) else [next(scope.iter_elements())]
