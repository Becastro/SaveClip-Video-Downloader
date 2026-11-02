import pytest

from app.config import _concurrency_limit


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0", 1), ("1", 1), ("3", 3), ("4", 4), ("12", 4)],
)
def test_concurrency_setting_is_clamped_to_safe_range(value, expected):
    assert _concurrency_limit(value) == expected


def test_concurrency_setting_rejects_non_integer_values():
    with pytest.raises(ValueError):
        _concurrency_limit("many")
