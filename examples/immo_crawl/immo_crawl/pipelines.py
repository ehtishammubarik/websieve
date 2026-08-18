import os
import psycopg2
from scrapy.exceptions import DropItem
from datetime import datetime


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


class WriteToDB(object):
    def open_spider(self, spider):
        self.conn = psycopg2.connect(host=hostname, user=username, password=password, dbname=database)
        self.cur = self.conn.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.conn.close()

    def process_item(self, item, spider):
        self.cur.execute('INSERT INTO eva_data (address, zip, city, canton, price_chf, '
                         'rooms, area_m2, floor, utilities_chf, date_available, date_scraped, date_last_seen, url) '
                         'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);',
                         (item['address'], item['zip_code'], item['city'], item['canton'],
                          item['price_chf'], item['rooms'], item['area_m2'], item['floor'],
                          item['utilities_chf'], item['date_available'], item['date_scraped'],
                          item['date_last_seen'], item['url']))
        self.cur.execute('INSERT INTO eva_prices (url, date, price_chf) VALUES (%s, %s, %s);',
                         (item['url'], item['date_scraped'], item['price_chf']))
        self.conn.commit()
        return item


class SetDefaultValues(object):
    def process_item(self, item, spider):
        item['area_m2'] = item.get('area_m2', None)
        item['floor'] = item.get('floor', None)
        item['utilities_chf'] = item.get('utilities_chf', None)
        item['date_available'] = item.get('date_available', None)
        return item


class CleanData(object):
    def process_item(self, item, spider):
        try:
            item['price_chf'] = int(item['price_chf'])
        except (ValueError, KeyError):
            raise DropItem

        if item['area_m2'] == '':
            item['area_m2'] = None
        elif item['area_m2']:
            try:
                item['area_m2'] = int(item['area_m2'])
            except ValueError:
                item['area_m2'] = None

        if item['utilities_chf'] == '':
            item['utilities_chf'] = None
        elif item['utilities_chf']:
            try:
                item['utilities_chf'] = int(item['utilities_chf'])
            except ValueError:
                item['utilities_chf'] = None

        if item['floor'] == '':
            item['floor'] = None

        try:
            item['date_available'] = datetime.strptime(item['date_available'], '%d.%m.%Y')
        except (ValueError, TypeError, KeyError):
            item['date_available'] = None

        return item


class DataValidation(object):
    def process_item(self, item, spider):
        try:
            if not (item['zip_code'].isdecimal() and len(item['zip_code']) == 4):
                raise DropItem
        except KeyError:
            raise DropItem

        try:
            if item['rooms'] == '':
                raise DropItem
        except KeyError:
            raise DropItem

        return item


class PriceCheckValidation(object):
    def process_item(self, item, spider):
        try:
            item['price_chf'] = int(item['price_chf'])
        except (ValueError, KeyError):
            raise DropItem

        return item


class WritePrice(object):
    def open_spider(self, spider):
        self.conn = psycopg2.connect(host=hostname, user=username, password=password, dbname=database)
        self.cur = self.conn.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.conn.close()

    def process_item(self, item, spider):
        self.cur.execute('INSERT INTO eva_prices (url, date, price_chf) VALUES (%s, %s, %s);',
                         (item['url'], item['date'], item['price_chf']))
        self.conn.commit()
        return item


class ComparePrice(object):
    def open_spider(self, spider):
        self.conn = psycopg2.connect(host=hostname, user=username, password=password, dbname=database)
        self.cur = self.conn.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.conn.close()

    def process_item(self, item, spider):
        self.cur.execute('SELECT price_chf FROM eva_prices WHERE url = %s ORDER BY date desc',
                         (item['url'], ))
        price = self.cur.fetchone()[0]
        if item['price_chf'] == price:
            raise DropItem
        else:
            return item
