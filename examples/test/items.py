from pydantic import BaseModel, Field


class BookItem(BaseModel):
    title: str
    price: str = ""
    availability: str = Field(
        default="", description="Raw availability text from the listing page."
    )


__all__ = ["BookItem"]
