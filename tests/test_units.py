from decimal import Decimal

from app.extract.units import normalize_digits, normalize_text, normalize_unit


def test_normalize_unit_length_aliases():
    assert normalize_unit("m").factor == Decimal("1")
    assert normalize_unit("متر").base_unit == "m"
    assert normalize_unit("mm").factor == Decimal("0.001")
    assert normalize_unit("مم").base_unit == "m"


def test_normalize_unit_area_and_volume_arabic_superscripts():
    assert normalize_unit("م²").base_unit == "m2"
    assert normalize_unit("م3").base_unit == "m3"
    assert normalize_unit("متر مكعب").base_unit == "m3"


def test_normalize_unit_mass_factor():
    info = normalize_unit("طن")
    assert info.known and info.factor == Decimal("1000") and info.base_unit == "kg"


def test_normalize_unit_fixed_price_arabic():
    assert normalize_unit("مقطوعية").dimension == "fixed"
    assert normalize_unit("L.S.").dimension == "fixed"


def test_unknown_unit_reported():
    info = normalize_unit("test")
    assert not info.known and info.base_unit == "test"


def test_normalize_digits_arabic_indic():
    assert normalize_digits("٨٥٠") == "850"
    assert normalize_digits("١٢٫٥") == "12٫5"  # decimal separator left intact
    assert normalize_digits("125.5") == "125.5"


def test_normalize_text_strips_diacritics_and_tatweel():
    assert normalize_text("الكـمِّيّة") == "الكمية"
