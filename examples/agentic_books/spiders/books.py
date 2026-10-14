"""The model chooses which links and fields to inspect; no fixed follow rules."""

from pydantic import BaseModel

from webuse import AgenticSpider, AgentLimits


class Book(BaseModel):
    title: str
    price: str
    availability: str


class Books(AgenticSpider):
    name = "books"
    start_urls = ["https://books.toscrape.com/"]
    allowed_domains = {"books.toscrape.com"}
    goal = (
        "Collect books from the catalog with their title, price, and availability. "
        "Follow pagination and product links as needed. Preserve prices as shown."
    )
    item_model = Book
    limits = AgentLimits(max_tokens=500_000)
