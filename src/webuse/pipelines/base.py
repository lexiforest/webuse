from pydantic import BaseModel


class ItemPipeline:
    def open_spider(self) -> None:
        return None

    def process_item(self, item: BaseModel) -> BaseModel | None:
        return item

    def close_spider(self) -> None:
        return None


class AsyncItemPipeline:
    """Async item processing and lifecycle hooks for AsyncSpider."""

    async def open_spider(self) -> None:
        return None

    async def process_item(self, item: BaseModel) -> BaseModel | None:
        return item

    async def close_spider(self) -> None:
        return None


__all__ = ["ItemPipeline", "AsyncItemPipeline"]
