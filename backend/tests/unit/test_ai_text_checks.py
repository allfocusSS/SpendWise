"""check_free_text: the only provider-written text (advice) cannot carry figures or claims."""

import pytest

from app.ai.text_checks import UngroundedTextError, check_free_text, normalize_text


def rejected(text: str, reason: str) -> None:
    with pytest.raises(UngroundedTextError, match=reason):
        check_free_text(text)


class TestAllowedAdvice:
    @pytest.mark.parametrize(
        "text",
        [
            "Review your largest categories to see where you can cut back.",
            "Try saving on groceries by planning meals.",
            "Building savings is easier with a monthly plan.",
            "Попробуйте планировать покупки заранее.",
            "Let your coffee spending go down by brewing at home.",
            "One small habit at a time works well.",  # "one" is deliberately allowed
        ],
    )
    def test_plain_advice_is_accepted(self, text: str) -> None:
        assert check_free_text(text) == text

    def test_returns_normalised_text_without_invisible_characters(self) -> None:
        assert check_free_text("Plan\u200b ahead\u00ad.") == "Plan ahead."
        assert normalize_text("ｆｕｌｌｗｉｄｔｈ") == "fullwidth"


class TestNumericCharacters:
    @pytest.mark.parametrize(
        "char",
        [
            "5",  # ASCII
            "½",  # vulgar fraction (isdigit() is False)
            "¾",
            "Ⅻ",  # roman numeral (isdigit() is False)
            "Ⅳ",
            "ⅻ",
            "五",  # CJK numeral (isdigit() is False)
            "千",
            "万",
            "①",  # circled digit
            "²",  # superscript
            "５",  # fullwidth digit
            "٤",  # Arabic-Indic digit
            "۵",  # extended Arabic-Indic digit
            "४",  # Devanagari digit
            "௰",  # Tamil number ten (isdigit() is False)
            "𝟕",  # mathematical bold digit (NFKC → 7)
        ],
    )
    def test_any_numeric_character_is_rejected(self, char: str) -> None:
        rejected(f"Cut back by {char} next month.", "numeric character")


class TestRomanNumerals:
    @pytest.mark.parametrize(
        "text", ["Keep going for XII weeks.", "IV tips for you.", "Since MMXXVI."]
    )
    def test_ascii_roman_numerals_are_rejected(self, text: str) -> None:
        rejected(text, "Roman numeral")

    @pytest.mark.parametrize("text", ["I think you can plan ahead.", "Mix and match meals."])
    def test_ordinary_words_are_not_mistaken_for_roman_numerals(self, text: str) -> None:
        assert check_free_text(text) == text


class TestCurrencyAndPercent:
    @pytest.mark.parametrize(
        "symbol", ["₸", "$", "€", "£", "¥", "₹", "₩", "₽", "¢", "₺", "﷼", "＄"]
    )
    def test_currency_symbols_are_rejected_by_unicode_category(self, symbol: str) -> None:
        rejected(f"Spend less {symbol} on taxis.", "currency symbol")

    @pytest.mark.parametrize(
        "marker", ["%", "％", "﹪", "\u066a", "\u2030", "\u2031", "\u0609", "\u060a"]
    )
    def test_percent_markers_are_rejected(self, marker: str) -> None:
        rejected(f"Aim lower {marker} next time.", "percent marker")

    @pytest.mark.parametrize(
        "word",
        [
            "tenge",
            "теңге",
            "тенге",
            "тңг",
            "тг",
            "tg",
            "KZT",
            "percent",
            "per cent",
            "pct",
            "bps",
            "basis points",
            "процентов",
            "пайыз",
            "dollars",
            "рублей",
        ],
    )
    def test_unit_words_are_rejected(self, word: str) -> None:
        rejected(f"Plan a few {word} for treats.", "unit word")


class TestNumberWords:
    @pytest.mark.parametrize(
        "word",
        [
            # English
            "zero",
            "two",
            "fifteen",
            "fifty",
            "hundred",
            "thousand",
            "million",
            "billion",
            "trillion",
            "dozen",
            "half",
            "halved",
            "a quarter",
            "a third",
            "fifths",
            "twice",
            "doubled",
            "triple",
            # Russian
            "ноль",
            "две",
            "пять",
            "одиннадцать",
            "пятьдесят",
            "сто",
            "тысяча",
            "миллион",
            "миллиард",
            "триллион",
            "половина",
            "четверть",
            "треть",
            "вдвое",
            "дважды",
            # Kazakh
            "екі",
            "үш",
            "бес",
            "елу",
            "жүз",
            "мың",
            "жарты",
        ],
    )
    def test_number_words_are_rejected(self, word: str) -> None:
        rejected(f"Put {word} aside.", "number word")


class TestDirectionClaims:
    @pytest.mark.parametrize(
        "text",
        [
            "Great news: you saved a lot this month.",
            "You had a nice surplus.",
            "Watch out for the deficit.",
            "Your spending increased.",
            "Costs decreased nicely.",
            "Spending rose again.",
            "Spending fell sharply.",
            "Your income exceeded your expenses.",
            "Great job staying in the black.",
            "You are in the red.",
            "You have money left over.",
            "Your spending went down.",
            "Costs have gone up.",
            "Вы сэкономили деньги.",
            "Расходы выросли.",
        ],
    )
    def test_direction_claims_are_rejected(self, text: str) -> None:
        rejected(text, "direction claim")


class TestObfuscation:
    def test_zero_width_characters_cannot_hide_a_number_word(self) -> None:
        rejected("About a thou\u200bsand more.", "number word")
        rejected("About a thou\u00adsand more.", "number word")  # soft hyphen
        rejected("You sa\u200dved a lot.", "direction claim")  # zero-width joiner

    def test_mixed_script_homoglyphs_are_rejected(self) -> None:
        rejected("About a thоusand more.", "mixes Latin and Cyrillic")  # Cyrillic о
        rejected("You ѕaved a lot.", "mixes Latin and Cyrillic")  # Cyrillic ѕ

    def test_fullwidth_letters_are_normalised_before_checking(self) -> None:
        rejected("ｔｈｏｕｓａｎｄ of reasons", "number word")
        rejected("ｓａｖｅｄ a lot", "direction claim")

    @pytest.mark.parametrize("text", ["Use {income} wisely.", "Use {{income}}.", "A } brace"])
    def test_braces_and_placeholders_are_rejected(self, text: str) -> None:
        rejected(text, "placeholders or braces")
