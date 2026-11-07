"""A minimal Scrapy spider that yields {"url", "html"} records.

It crawls the local fixture set served by `python -m http.server 8000
--directory fixtures`. It starts at index.html and follows same-host links to
the .html fixture pages, so the crawl stops at a handful of local pages.

The spider deliberately does not parse or clean the HTML: that is websieve's
job. It only captures the raw page so the pipeline downstream decides what
survives. Only 200 responses are yielded, so a missing link (like about.html)
cannot silently add an error page to the corpus.
"""

import scrapy


class SampleSpider(scrapy.Spider):
    name = "sample"

    start_urls = ["http://localhost:8000/index.html"]

    # .html pages that actually exist under fixtures/. Known up front so the
    # spider never follows a link into a 404.
    _fixture_pages = {
        "article-a.html",
        "article-b.html",
        "nav.html",
        "spam.html",
    }

    def parse(self, response):
        if response.status != 200:
            return

        # Yield the page itself first.
        yield {"url": response.url, "html": response.text}

        # Follow links to other local .html fixture pages.
        for href in response.css("a::attr(href)").getall():
            page = href.split("?")[0].split("#")[0].rsplit("/", 1)[-1]
            if page in self._fixture_pages and page not in response.url:
                yield response.follow(href, callback=self.parse)
