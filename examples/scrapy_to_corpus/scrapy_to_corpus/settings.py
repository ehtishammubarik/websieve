# Crawl-ethics settings for the example. See
# .claude/skills/crawl-ethics/SKILL.md for why each of these is non-negotiable.
BOT_NAME = "scrapy_to_corpus"

SPIDER_MODULES = ["scrapy_to_corpus.spiders"]
NEWSPIDER_MODULE = "scrapy_to_corpus.spiders"

# Honest user agent with a contact address, so an operator who wants the crawl
# to stop can reach the human responsible.
USER_AGENT = "websieve-example-scrapy-to-corpus (https://github.com/ehtishammubarik/websieve; contact: ehtisham@eprecisio.com)"

# Never flip this off to make a crawl finish faster. If a site disallows you,
# that is the answer.
ROBOTSTXT_OBEY = True

# Politeness.
DOWNLOAD_DELAY = 1
AUTOTHROTTLE_ENABLED = True
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# Local fixture crawl: nothing leaves localhost.
ROBOTSTXT_OBEY = True

# Feed export: JSONL, one record per line, in websieve's input shape.
FEED_EXPORTERS = {
    "jsonlines": "scrapy.exporters.JsonLinesItemExporter",
}
