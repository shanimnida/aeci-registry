"""core.capitalization is the one place name/address title-casing happens
(see people.models.Person.save() and Household.save()). Exercised directly
here, field-blind, so every edge case the volunteer's "capitalize each
word" request runs into is pinned down in one spot rather than scattered
across model-level tests.
"""

from core.capitalization import capitalize_suffix, capitalize_words


# -- already shouting: the ordinary case -------------------------------


def test_a_simple_all_caps_name_is_title_cased():
    assert capitalize_words("MARK JEROME") == "Mark Jerome"


def test_an_all_caps_address_is_title_cased_word_by_word():
    assert capitalize_words("LA TRINIDAD, BENGUET") == "La Trinidad, Benguet"


# -- already correct input: must not be mangled -------------------------


def test_mixed_case_input_is_left_alone():
    """A user typing "McDonald" in the admin must not have it rewritten --
    only text that is currently shouting is touched at all."""
    assert capitalize_words("McDonald") == "McDonald"


def test_lowercase_input_is_left_alone():
    assert capitalize_words("dela Cruz") == "dela Cruz"


def test_a_single_already_lowercase_letter_is_left_alone():
    assert capitalize_words("a") == "a"


# -- acronyms and codes inside addresses ---------------------------------


def test_a_purok_code_with_a_digit_is_left_alone():
    assert capitalize_words("KC-109 CRUZ, LA TRINIDAD, BENGUET") == "KC-109 Cruz, La Trinidad, Benguet"


def test_another_digit_bearing_code_is_left_alone():
    assert capitalize_words("OB-4-77 BANIG, TAWANG") == "OB-4-77 Banig, Tawang"


def test_a_dotted_initialism_with_no_vowels_is_left_alone():
    assert capitalize_words("ENDS IN B.G.H") == "Ends In B.G.H"


def test_a_bare_no_vowel_acronym_is_left_alone():
    assert capitalize_words("BGHMC") == "BGHMC"


def test_a_short_real_word_next_to_a_code_is_still_title_cased():
    """"LA" precedes a digit-bearing code in real data, but it is an
    ordinary word (it has a vowel) and must still become "La"."""
    assert capitalize_words("LA TRINIDAD") == "La Trinidad"


# -- apostrophes and hyphens ---------------------------------------------


def test_an_apostrophe_name_capitalizes_the_letter_after_it_too():
    assert capitalize_words("O'BRIEN") == "O'Brien"


def test_a_hyphenated_name_capitalizes_both_halves():
    assert capitalize_words("MARY-JANE") == "Mary-Jane"


# -- Filipino name particles: every word capitalized, no exceptions -----


def test_dela_cruz_capitalizes_both_words():
    assert capitalize_words("DELA CRUZ") == "Dela Cruz"


def test_del_rosario_capitalizes_both_words():
    assert capitalize_words("DEL ROSARIO") == "Del Rosario"


def test_de_guzman_capitalizes_both_words():
    assert capitalize_words("DE GUZMAN") == "De Guzman"


# -- blank, single character, trailing space -----------------------------


def test_a_blank_field_stays_blank():
    assert capitalize_words("") == ""


def test_a_single_shouting_letter_is_unchanged():
    assert capitalize_words("A") == "A"


def test_a_trailing_space_is_preserved():
    assert capitalize_words("MARK ") == "Mark "


def test_a_leading_space_is_preserved():
    assert capitalize_words(" MARK") == " Mark"


# -- suffix: Roman numerals must not become title-cased words -----------


def test_suffix_iii_is_not_mangled_into_iii_lowercase():
    assert capitalize_suffix("III") == "III"


def test_suffix_ii_stays_upper():
    assert capitalize_suffix("II") == "II"


def test_suffix_iv_stays_upper():
    assert capitalize_suffix("IV") == "IV"


def test_suffix_v_stays_upper():
    assert capitalize_suffix("V") == "V"


def test_suffix_jr_is_title_cased():
    assert capitalize_suffix("JR") == "Jr"


def test_suffix_jr_with_period_is_title_cased():
    assert capitalize_suffix("JR.") == "Jr."


def test_suffix_sr_is_title_cased():
    assert capitalize_suffix("SR") == "Sr"


def test_suffix_already_correct_is_left_alone():
    assert capitalize_suffix("Jr.") == "Jr."


def test_suffix_blank_stays_blank():
    assert capitalize_suffix("") == ""
