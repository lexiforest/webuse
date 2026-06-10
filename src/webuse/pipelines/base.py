from pydantic import BaseModel


class Pipeline:
    def open_spider(self) -> None:
        return None

    def process_item(self, item: BaseModel) -> BaseModel | None:
        return item

    def close_spider(self) -> None:
        return None


__all__ = ["Pipeline"]
