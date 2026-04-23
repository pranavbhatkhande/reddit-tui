"""Tests for utility formatters."""
from __future__ import annotations

import time

from reddit_tui.utils import escape_markup, format_age, format_score


class TestEscapeMarkup:
    def test_empty(self) -> None:
        assert escape_markup("") == ""

    def test_no_brackets(self) -> None:
        assert escape_markup("hello world") == "hello world"

    def test_open_bracket_escaped(self) -> None:
        assert escape_markup("[red]bold[/]") == "\\[red]bold\\[/]"

    def test_close_bracket_left_alone(self) -> None:
        # We only need to escape opens; closes are harmless.
        assert "]" in escape_markup("foo]bar")


class TestFormatScore:
    def test_small(self) -> None:
        assert format_score(0) == "0"
        assert format_score(42) == "42"
        assert format_score(999) == "999"

    def test_thousands(self) -> None:
        assert format_score(1000) == "1.0k"
        assert format_score(15400) == "15.4k"

    def test_millions(self) -> None:
        assert format_score(1_500_000) == "1.5M"


class TestFormatAge:
    def test_zero(self) -> None:
        assert format_age(0) == "?"

    def test_seconds(self) -> None:
        now = time.time()
        assert format_age(now - 30).endswith("s")

    def test_minutes(self) -> None:
        now = time.time()
        assert format_age(now - 600).endswith("m")

    def test_hours(self) -> None:
        now = time.time()
        assert format_age(now - 7200).endswith("h")

    def test_days(self) -> None:
        now = time.time()
        assert format_age(now - 86400 * 3).endswith("d")
