"""Validation for the only free text a provider may write: optional advice.

Advice must not state figures or financial direction; those come from backend-rendered
sentences (app/ai/facts.py). Invisible formatting characters (category Cf) are removed first.
Character checks then run on BOTH that text and its Unicode NFKC normalisation, because NFKC can
hide things as well as reveal them: it turns fullwidth "５" into "5" and "ｓａｖｅｄ" into "saved",
but also turns "Ⅻ" into the letters "XII" and the Rial sign "﷼" into a word. Word checks run on
the normalised text.

Rejected (always, by character class):
- any character with a numeric value (str.isnumeric): 5, ½, Ⅻ, 五, ①, ², ٤ …
- any currency symbol (Unicode category Sc): ₸ $ € ¥ ₹ ₩ ₽ …
- percent markers: % (incl. fullwidth/small forms after NFKC), Arabic percent, per-mille,
  per-ten-thousand and Arabic per-mille/per-ten-thousand signs
- braces (no placeholders in advice)
- words that mix Latin and Cyrillic letters (homoglyph tricks such as "thоusand")
- Roman numerals written in capital letters ("XII", "IV"; best-effort, 2+ letters)

Rejected (best-effort word lists, cannot cover every phrasing):
- currency/unit words (tenge, теңге, тңг, tg, KZT, percent, процент, пайыз, …)
- number words in English, Russian and Kazakh (thousand, a quarter, миллиард, мың, …)
- direction claims (saved, surplus, deficit, increased, "in the black", "went down", …)
"""

import re
import unicodedata


class UngroundedTextError(ValueError):
    """Provider output broke the rules; it must not be shown to the user."""


PERCENT_MARKERS = frozenset("%\u066a\u2030\u2031\u0609\u060a")

_UNIT_WORDS = re.compile(
    r"\b(?:kzt|tenge|теңге|тенге|тңг|тг|tg|usd|eur|rub|dollars?|euros?|руб\w*|доллар\w*|евро"
    r"|percent|per\s*cent|pct|bps|basis\s+points?|процент\w*|пайыз\w*)\b",
    re.IGNORECASE,
)

_NUMBER_WORDS = re.compile(
    r"\b(?:"
    # English
    r"zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty"
    r"|ninety|hundreds?|thousands?|millions?|billions?|trillions?|dozens?|half|halves|halved"
    r"|quarters?|thirds?|fifths?|tenths?|twice|thrice|double[ds]?|triple[ds]?|quadruple[ds]?"
    # Russian
    r"|ноль|нуля|два|две|двух|три|трёх|трех|четыре|пять|шесть|семь|восемь|девять|десять"
    r"|\w+надцать|двадцать|тридцать|сорок|пятьдесят|шестьдесят|семьдесят|восемьдесят|девяносто"
    r"|сто|двести|триста|четыреста|пятьсот|шестьсот|семьсот|восемьсот|девятьсот|тысяч\w*"
    r"|миллион\w*|миллиард\w*|триллион\w*|половин\w*|четверт\w*|трет\w*|вдвое|втрое|дважды"
    r"|трижды"
    # Kazakh
    r"|екі|үш|төрт|бес|алты|жеті|сегіз|тоғыз|жиырма|отыз|қырық|елу|алпыс|жетпіс|сексен"
    r"|тоқсан|жүз|мың|жарты"
    r")\b",
    re.IGNORECASE,
)

# Claims about the direction of money belong to backend sentences. Advice vocabulary such as
# "save", "saving" and "savings" stays allowed ("Try saving on groceries").
_DIRECTION_CLAIMS = re.compile(
    r"\b(?:saved|surplus(?:es)?|deficits?|profits?|loss(?:es)?|overspen[dt]\w*|underspent"
    r"|increas\w*|decreas\w*|rose|risen|fell|fallen|grew|grown|growth|dropped|declin\w*"
    r"|exceed\w*|in\s+the\s+(?:black|red)|left\s+over|(?:went|gone)\s+(?:up|down)"
    r"|сэкономил\w*|профицит\w*|дефицит\w*|вырос\w*|снизил\w*|увеличил\w*|уменьшил\w*"
    r"|превысил\w*)\b",
    re.IGNORECASE,
)


# Uppercase Roman numerals of 2+ letters ("XII", "IV", "MMXXVI"). Single "I"/"V" are words too.
_ROMAN_NUMERAL = re.compile(
    r"\b(?=[MDCLXVI]{2,}\b)M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\b"
)


def strip_invisible(text: str) -> str:
    return "".join(char for char in text if unicodedata.category(char) != "Cf")


def normalize_text(text: str) -> str:
    """NFKC-normalise and drop invisible formatting characters (zero-width space, soft hyphen…)."""
    return strip_invisible(unicodedata.normalize("NFKC", strip_invisible(text)))


def _scripts(word: str) -> set[str]:
    scripts = set()
    for char in word:
        if char.isalpha():
            name = unicodedata.name(char, "")
            if name.startswith("LATIN"):
                scripts.add("latin")
            elif name.startswith("CYRILLIC"):
                scripts.add("cyrillic")
    return scripts


def check_free_text(text: str) -> str:
    """Return the normalised text, or raise UngroundedTextError explaining the violation."""
    visible = strip_invisible(text)
    cleaned = normalize_text(text)

    for char in visible + cleaned:
        if char.isnumeric():
            raise UngroundedTextError(f"Advice contains a numeric character ({char!r})")
        if unicodedata.category(char) == "Sc":
            raise UngroundedTextError(f"Advice contains a currency symbol ({char!r})")
        if char in PERCENT_MARKERS:
            raise UngroundedTextError(f"Advice contains a percent marker ({char!r})")
        if char in "{}":
            raise UngroundedTextError("Advice may not contain placeholders or braces")
    for word in re.findall(r"\w+", cleaned):
        if len(_scripts(word)) > 1:
            raise UngroundedTextError(f"Advice mixes Latin and Cyrillic letters in {word!r}")
    if match := _ROMAN_NUMERAL.search(cleaned):
        raise UngroundedTextError(f"Advice contains a Roman numeral ({match.group(0)!r})")
    if match := _UNIT_WORDS.search(cleaned):
        raise UngroundedTextError(f"Advice contains a unit word ({match.group(0)!r})")
    if match := _NUMBER_WORDS.search(cleaned):
        raise UngroundedTextError(f"Advice contains a number word ({match.group(0)!r})")
    if match := _DIRECTION_CLAIMS.search(cleaned):
        raise UngroundedTextError(f"Advice contains a direction claim ({match.group(0)!r})")
    return cleaned
