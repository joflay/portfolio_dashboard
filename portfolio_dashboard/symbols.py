from __future__ import annotations

from typing import Any


SYMBOL_ALIASES = {
    "SATS": "ECHO",
}


def canonical_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    return SYMBOL_ALIASES.get(symbol, symbol)


def aliases_for_symbol(value: Any) -> set[str]:
    canonical = canonical_symbol(value)
    aliases = {alias for alias, target in SYMBOL_ALIASES.items() if target == canonical}
    return {canonical, *aliases} if canonical else set()


def lookup_symbols(values: set[str]) -> set[str]:
    output: set[str] = set()
    for value in values:
        output.update(aliases_for_symbol(value))
    return output
