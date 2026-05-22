from __future__ import annotations

import pytest

from app.core.rut import format_rut, validate_rut


class TestValidateRut:
    def test_valid_rut_12345678_5(self) -> None:
        assert validate_rut("12345678-5") is True

    def test_valid_rut_11111111_1(self) -> None:
        assert validate_rut("11111111-1") is True

    def test_valid_rut_15225841_0(self) -> None:
        assert validate_rut("15225841-0") is True

    def test_valid_rut_with_k(self) -> None:
        assert validate_rut("10000013-K") is True

    def test_valid_rut_lowercase_k(self) -> None:
        assert validate_rut("10000013-k") is True

    def test_invalid_rut_wrong_dv(self) -> None:
        assert validate_rut("12345678-9") is False

    def test_invalid_rut_all_zeros_wrong_dv(self) -> None:
        assert validate_rut("00000000-1") is False

    def test_invalid_rut_empty_string(self) -> None:
        assert validate_rut("") is False

    def test_invalid_rut_single_char(self) -> None:
        assert validate_rut("1") is False

    def test_valid_rut_with_dots(self) -> None:
        assert validate_rut("12.345.678-5") is True

    def test_valid_rut_with_dots_and_k(self) -> None:
        assert validate_rut("10.000.013-K") is True

    def test_rut_body_not_digits(self) -> None:
        assert validate_rut("abcdefgh-K") is False

    def test_rut_with_only_spaces(self) -> None:
        assert validate_rut("   ") is False


class TestFormatRut:
    def test_format_basic(self) -> None:
        assert format_rut("12345678-5") == "12345678-5"

    def test_format_strips_dots(self) -> None:
        assert format_rut("12.345.678-5") == "12345678-5"

    def test_format_uppercase_k(self) -> None:
        assert format_rut("10000013-k") == "10000013-K"

    def test_format_plain_digits(self) -> None:
        assert format_rut("123456785") == "12345678-5"

    def test_format_short_input_returned_as_is(self) -> None:
        assert format_rut("1") == "1"

    def test_format_empty_string(self) -> None:
        assert format_rut("") == ""
