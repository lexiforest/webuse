# webuse crawl examples/quotes --spider quotes -o quotes.jsonl

import webuse


class QuotesSpider(webuse.Spider):
    name = "quotes"
    start_urls = [
        "https://quotes.toscrape.com/tag/humor/",
    ]

    def parse(self, response):
        for quote in response.find_all(css="div.quote"):
            yield {
                "author": quote.find(css="small.author").text(),
                "text": quote.find(css="span.text").text(),
            }

        next_page = response.find(css="li.next a")
        if next_page is not None:
            yield response.follow(next_page.attr("href"))
