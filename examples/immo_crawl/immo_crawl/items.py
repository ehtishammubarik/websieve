from scrapy.item import Item, Field
from scrapy.loader import ItemLoader
from itemloaders.processors import TakeFirst, Compose


def first_element(str_list):
    try:
        return str_list[0]
    except IndexError:
        return ''


def second_element(str_list):
    try:
        return str_list[1]
    except IndexError:
        return ''


def third_element(str_list):
    try:
        return str_list[2]
    except IndexError:
        return ''


def fourth_element(str_list):
    try:
        return str_list[3]
    except IndexError:
        return ''


def fifth_element(str_list):
    try:
        return str_list[4]
    except IndexError:
        return ''


def remove_comma(string):
    return string.strip(', ')


def remove_chf(string):
    return string.strip('CHF .—')


def remove_room(string):
    return string.strip(' Zimer')


def remove_m2(string):
    return string.strip(' m²')


class ImmoCrawlItem(Item):
    address = Field()
    zip_code = Field()
    city = Field()
    canton = Field()
    rooms = Field()
    area_m2 = Field()
    price_chf = Field()
    date_scraped = Field()
    date_available = Field()
    date_last_seen = Field()
    floor = Field()
    utilities_chf = Field()
    url = Field()


class ImmoScoutLoader(ItemLoader):
    default_output_processor = TakeFirst()

    address_in = Compose(first_element)
    zip_code_in = Compose(second_element)
    city_in = Compose(fourth_element)
    canton_in = Compose(fifth_element, remove_comma)
    rooms_in = Compose(first_element, remove_room)
    area_m2_in = Compose(third_element, remove_m2)
    price_chf_in = Compose(first_element, remove_chf)
    date_available_in = Compose(second_element)
    floor_in = Compose(second_element)
    utilities_chf_in = Compose(second_element, remove_chf)


class PriceCheckItem(Item):
    url = Field()
    date = Field()
    price_chf = Field()


class PriceCheckLoader(ItemLoader):
    default_output_processor = TakeFirst()
    price_chf_in = Compose(first_element, remove_chf)
