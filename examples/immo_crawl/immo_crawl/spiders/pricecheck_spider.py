import os
import scrapy
import psycopg2
from datetime import date, timedelta
from immo_crawl.items import PriceCheckItem, PriceCheckLoader


# Database connection. Read from the environment: never commit credentials.
# See SECURITY.md. Set these in your Scrapyd unit file or container env.
hostname = os.environ.get('CRAWL_DB_HOST', 'localhost')
username = os.environ.get('CRAWL_DB_USER', 'postgres')
password = os.environ.get('CRAWL_DB_PASSWORD')
database = os.environ.get('CRAWL_DB_NAME', 'eva_db')

if not password:
    raise RuntimeError(
        'CRAWL_DB_PASSWORD is not set. Export it before running the spider.'
    )


class PricecheckSpider(scrapy.Spider):
    name = 'pricecheck'
    custom_settings = {
        'ITEM_PIPELINES': {
            'immo_crawl.pipelines.PriceCheckValidation': 100,
            'immo_crawl.pipelines.ComparePrice': 150,
            'immo_crawl.pipelines.WritePrice': 200
        }}

    def start_requests(self):
        check_date = date.today() - timedelta(days=7)
        conn = psycopg2.connect(host=hostname, user=username, password=password, dbname=database)
        with conn.cursor() as cur:
            cur.execute('SELECT url FROM eva_data WHERE date_last_seen > %s;', (check_date, ))
            pricecheck_urls = [url[0] for url in cur.fetchall()]
        conn.close()

        for url in pricecheck_urls:
            yield scrapy.Request(url, callback=self.parse)

    def parse(self, response, **kwargs):
        loader = PriceCheckLoader(item=PriceCheckItem(), response=response)
        loader.add_value('url', response.request.url.split('?')[0])
        loader.add_value('date', date.today())
        loader.add_xpath('price_chf', '//article[1]/div/h2/text()')

        price_item = loader.load_item()

        yield price_item
