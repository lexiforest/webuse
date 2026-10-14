import webuse
from pydantic import BaseModel, Field


class BookItem(BaseModel):
    title: str
    price: str = ""
    availability: str = Field(
        default="", description="Raw availability text from the listing page."
    )


class CleanBookPipeline(webuse.ItemPipeline):
    def process_item(self, item: BookItem):
        return item


class BooksSpider(webuse.Spider):
    spider_config_path = "spiders/books.yaml"
    item_model = BookItem


def main():
    BooksSpider().run()


if __name__ == "__main__":
    main()
