import inspect
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .exceptions import SignalError


Handler = Callable[..., Any]


class SignalBus:
    """Register handlers by signal name and dispatch keyword payloads in order.

    Each dispatch uses a snapshot of the registered handlers. Payload keys are
    filtered to each handler's accepted keyword arguments unless it accepts
    ``**kwargs`` or its signature cannot be inspected. Handler exceptions
    propagate to the caller and stop dispatch to remaining handlers.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def connect(self, signal: str, handler: Handler) -> Handler:
        if handler not in self._handlers[signal]:
            self._handlers[signal].append(handler)
        return handler

    def disconnect(self, signal: str, handler: Handler) -> None:
        if handler in self._handlers.get(signal, []):
            self._handlers[signal].remove(handler)

    def handlers(self, signal: str) -> list[Handler]:
        return list(self._handlers.get(signal, []))

    def send(self, signal: str, **kwargs: Any) -> list[Any]:
        results: list[Any] = []
        for handler in self.handlers(signal):
            result = handler(**_handler_kwargs(handler, kwargs))
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if close is not None:
                    close()
                raise SignalError(
                    f"Signal handler for {signal!r} returned an awaitable; use asend()"
                )
            results.append(result)
        return results

    async def asend(self, signal: str, **kwargs: Any) -> list[Any]:
        results: list[Any] = []
        for handler in self.handlers(signal):
            result = handler(**_handler_kwargs(handler, kwargs))
            if inspect.isawaitable(result):
                result = await result
            results.append(result)
        return results


def _handler_kwargs(handler: Handler, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return kwargs
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return kwargs
    return {
        name: kwargs[name]
        for name, parameter in signature.parameters.items()
        if name in kwargs
        and parameter.kind
        in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }


__all__ = ["SignalBus"]
