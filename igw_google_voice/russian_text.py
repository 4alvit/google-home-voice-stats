"""Conservative Russian speech normalization, independent of English Kitten rules."""
from decimal import Decimal, InvalidOperation
import re

MAX_TEXT = 1200
NUMBER = r'[−-]?\d+(?:[.,]\d+)?'
ONES = ('', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять')
TEENS = ('десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать',
         'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать')
TENS = ('', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто')
HUNDREDS = ('', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот', 'семьсот', 'восемьсот', 'девятьсот')
SCALES = ((10**12, ('триллион', 'триллиона', 'триллионов'), False),
          (10**9, ('миллиард', 'миллиарда', 'миллиардов'), False),
          (10**6, ('миллион', 'миллиона', 'миллионов'), False),
          (1000, ('тысяча', 'тысячи', 'тысяч'), True))


def integer_words(number, feminine=False):
    if number == 0:
        return 'ноль'
    if number < 0:
        return 'минус ' + integer_words(-number, feminine)
    words = []
    for scale, forms, gender in SCALES:
        group, number = divmod(number, scale)
        if group:
            words.extend((integer_words(group, gender), unit_words(str(group), forms)))
    if number >= 100:
        words.append(HUNDREDS[number // 100])
        number %= 100
    if 10 <= number < 20:
        words.append(TEENS[number - 10])
    else:
        if number >= 20:
            words.append(TENS[number // 10])
        if number % 10:
            one = number % 10
            words.append(('одна' if one == 1 else 'две') if feminine and one in (1, 2) else ONES[one])
    return ' '.join(words)
# Genitive singular is also used after a decimal fraction.
UNITS = {
    'кВт⋅ч': ('киловатт-час', 'киловатт-часа', 'киловатт-часов'),
    'кВт·ч': ('киловатт-час', 'киловатт-часа', 'киловатт-часов'),
    'кВтч': ('киловатт-час', 'киловатт-часа', 'киловатт-часов'),
    'kWh': ('киловатт-час', 'киловатт-часа', 'киловатт-часов'),
    'кВт': ('киловатт', 'киловатта', 'киловатт'),
    'kW': ('киловатт', 'киловатта', 'киловатт'),
    'Вт': ('ватт', 'ватта', 'ватт'), 'W': ('ватт', 'ватта', 'ватт'),
    'В': ('вольт', 'вольта', 'вольт'), 'V': ('вольт', 'вольта', 'вольт'),
    'А': ('ампер', 'ампера', 'ампер'), 'A': ('ампер', 'ампера', 'ампер'),
    '%': ('процент', 'процента', 'процентов'),
    '°C': ('градус Цельсия', 'градуса Цельсия', 'градусов Цельсия'),
    '°С': ('градус Цельсия', 'градуса Цельсия', 'градусов Цельсия'),
}


def number_words(value):
    value = value.replace('−', '-').replace(',', '.')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('Invalid speech number') from None
    if not number.is_finite() or abs(number) >= Decimal('1000000000000000'):
        raise ValueError('Speech number exceeds the supported range')
    if '.' not in value:
        return integer_words(int(number))
    left, right = value.lstrip('-').split('.')
    sign = 'минус ' if value.startswith('-') else ''
    if len(right) > 6:
        return sign + integer_words(int(left)) + ' запятая ' + ' '.join(integer_words(int(d)) for d in right)
    denominator = ('десятая', 'сотая', 'тысячная', 'десятитысячная', 'стотысячная', 'миллионная')[len(right) - 1]
    numerator = int(right)
    singular = numerator % 10 == 1 and numerator % 100 != 11
    return (sign + integer_words(int(left), True) + ' '
            + unit_words(left, ('целая', 'целых', 'целых')) + ' '
            + integer_words(numerator, True) + ' '
            + (denominator if singular else denominator[:-2] + 'ых'))


def unit_words(value, forms):
    normalized = value.replace('−', '-').replace(',', '.')
    if '.' in normalized:
        return forms[1]
    number = abs(int(normalized))
    return forms[2] if 11 <= number % 100 <= 14 else (
        forms[0] if number % 10 == 1 else forms[1] if 2 <= number % 10 <= 4 else forms[2])


def normalize_russian(text):
    if (not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT
            or any(ord(c) < 32 and c not in '\n\r\t' for c in text)
            or any(marker in text for marker in ('<', '>', '[', ']', '((('))):
        raise ValueError('Expected plain speech text of at most 1200 characters')
    # Thin/nonbreaking separators occur in rendered reports. Remove only groups
    # with exactly three digits so that ordinary numbers remain separate.
    text = re.sub(r'(?<=\d)[\u00a0\u202f](?=\d{3}(?:\D|$))', '', text)
    text = ' '.join(text.split())
    pattern = re.compile(r'(?<![\w.,])(' + NUMBER + r')\s*('
                         + '|'.join(re.escape(u) for u in UNITS) + r')(?!\w)')
    text = pattern.sub(lambda m: number_words(m[1]) + ' ' + unit_words(m[1], UNITS[m[2]]), text)
    text = re.sub(r'(?<![\w.,])' + NUMBER + r'(?!\w|[.,]\d)', lambda m: number_words(m[0]), text)
    if len(text) > MAX_TEXT:
        raise ValueError('Expanded speech text exceeds 1200 characters')
    return text
