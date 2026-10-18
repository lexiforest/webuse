from pydantic import BaseModel


class ItemPipeline:
    def open_spider(self) -> None:
        return None

    def process_item(self, item: BaseModel) -> BaseModel | None:
        return item

    def close_spider(self) -> None:
        return None


class AsyncItemPipeline:
    """Async hooks shared by an execution's workers.

    process_item calls may overlap. Protect shared state across awaits inside
    the pipeline. Lifecycle hooks run before workers start and after they stop.
    """

    async def open_spider(self) -> None:
        return None

    async def process_item(self, item: BaseModel) -> BaseModel | None:
        return item

    async def close_spider(self) -> None:
        return None


__all__ = ["ItemPipeline", "AsyncItemPipeline"]
