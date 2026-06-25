"""Shared decimal/money helpers.

These are pure utilities — no frappe dependency — so they can be imported
anywhere (tests, background workers, scripts) without a site context.

``safe_decimal`` reproduces the coercion rules of
``BankTransactionReconciliation._safe_decimal`` verbatim so that task R3 can
replace that method with a thin delegator without any behavior change.

Coercion rules (match the original exactly):
- ``None``                  → ``Decimal(default)``
- ``int`` / ``float``       → ``Decimal(str(value))``
- ``str``                   → strip all chars that are not ``[\\d.-]``, then
                              convert; empty-after-strip  → ``Decimal(default)``
- ``Decimal``               → returned unchanged
- other type                → ``Decimal(default)``
- ``InvalidOperation`` /
  ``ValueError``            → ``Decimal(default)``
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def safe_decimal(value, *, default="0") -> Decimal:
    """Coerce *value* to :class:`~decimal.Decimal`.

    Strips currency symbols, thousands-separator commas, and whitespace from
    strings before conversion.  Returns ``Decimal(default)`` for ``None``,
    unrecognized types, or values that cannot be parsed.

    Args:
        value:   The value to coerce (``str``, ``int``, ``float``,
                 ``Decimal``, or ``None``).
        default: String representation of the fallback value.  Defaults to
                 ``"0"``.

    Returns:
        A :class:`~decimal.Decimal` instance.
    """
    if value is None:
        return Decimal(default)

    try:
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        elif isinstance(value, str):
            # Strip everything except digits, '.', and '-'
            cleaned = re.sub(r"[^\d\.-]", "", value)
            return Decimal(cleaned) if cleaned else Decimal(default)
        elif isinstance(value, Decimal):
            return value
        else:
            return Decimal(default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def quantize_amount(value, *, places: int = 2, rounding: str = ROUND_HALF_UP) -> Decimal:
    """Round *value* to *places* decimal places using *rounding* mode.

    *value* is first coerced via :func:`safe_decimal` so ``str``, ``int``,
    ``float``, and ``None`` are all accepted.

    Args:
        value:    The amount to quantize.
        places:   Number of decimal places to keep.  Defaults to ``2``.
        rounding: Decimal rounding mode.  Defaults to
                  :data:`~decimal.ROUND_HALF_UP`.

    Returns:
        A :class:`~decimal.Decimal` rounded to *places* decimal places.
    """
    d = safe_decimal(value) if not isinstance(value, Decimal) else value
    quantizer = Decimal(10) ** -places
    return d.quantize(quantizer, rounding=rounding)
