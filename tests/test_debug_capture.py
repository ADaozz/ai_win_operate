import argparse

import pytest

from scripts.debug_capture import parse_hwnd


def test_parse_hwnd_accepts_decimal_and_hex() -> None:
    assert parse_hwnd("123") == 123
    assert parse_hwnd("0x7B") == 123


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_parse_hwnd_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_hwnd(value)
