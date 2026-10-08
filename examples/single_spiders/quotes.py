# webuse crawl quotes.py -o quotes.jsonl

import webuse


class QuotesSpider(webuse.Spider):
    name = "quotes"
    start_urls = [
        "https://quotes.toscrape.com/tag/humor/",
    ]

    def parse(self, response):
        for quote in response.css("div.quote"):
            yield {
                "author": quote.css_first("small.author").text(),
                "text": quote.css_first("span.text").text(),
            }

        next_page = response.css_first("li.next a")
        if next_page is not None:
            yield response.follow(next_page.attr("href"))
