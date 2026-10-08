import webuse


class BooksSpider(webuse.Spider):
    name = "books"
    start_urls = ["https://books.toscrape.com/"]
    allowed_domains = {"books.toscrape.com"}
    max_depth = 1

    follow = [
        webuse.FollowRule(css="a", same_domain=True),
    ]

    extract = {
        "fields": {
            "title": "title",
        },
    }


def main():
    BooksSpider().run()


if __name__ == "__main__":
    main()
