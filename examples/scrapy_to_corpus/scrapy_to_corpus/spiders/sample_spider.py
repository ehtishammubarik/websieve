"""A minimal Scrapy spider that yields {"url", "html"} records.

It crawls the local fixture set served by `python -m http.server 8000
--directory fixtures`. It starts at index.html and follows same-host links to
.html pages, so the crawl stops at a handful of fixture pages.

The spider deliberately does not parse or clean the HTML: that is websieve's
job. It only captures the raw page so the pipeline downstream decides what
survives.
"""

import scrapy


class SampleSpider(scrapy.Spider):
    name = "sample"

    start_urls = ["http://localhost:8000/index.html"]

    def parse(self, response):
        # Yield the page itself first.
        yield {"url": response.url, "html": response.text}

        # Follow links to other local .html fixture pages.
        for href in response.css("a::attr(href)").getall():
            if href.endswith(".html"):
                yield response.follow(href, callback=self.parse)
