import webuse
from pydantic import BaseModel


class CleanBookPipeline(webuse.Pipeline):
    def process_item(self, item: BaseModel):
        return item


__all__ = ["CleanBookPipeline"]
