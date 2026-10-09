import webuse


class BooksSpider(webuse.Spider):
    spider_config_path = "spiders/books.yaml"
    item_model = "items.BookItem"


def main():
    BooksSpider().run()


if __name__ == "__main__":
    main()
