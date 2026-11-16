"""Example workload: validate a batch of invoices (CPU-bound).

Run the benchmark on this file with:

    threadwise bench examples/parse_invoices.py

The only contract is `def run(seed) -> hashable`.  Each call must be
independent, because threadwise calls it from many workers at once.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

KIND = "cpu"
DESCRIPTION = "Parse and total a 120-invoice XML batch (regex + Decimal arithmetic)"

_INVOICE = """<?xml version="1.0"?>
<invoice id="{id}">
  <customer>{customer}</customer>
  <lines>
{lines}
  </lines>
  <tax rate="0.09"/>
</invoice>
"""

_LINE = '    <line sku="SKU-{sku}" qty="{qty}" unit="{unit}"/>'

_AMOUNT = re.compile(r'qty="(\d+)" unit="([\d.]+)"')
_TAX = re.compile(r'rate="([\d.]+)"')


def _make_invoice(seed: int) -> str:
    lines = [
        _LINE.format(sku=seed * 100 + i, qty=(seed * 7 + i) % 9 + 1, unit=f"{((seed + i) % 90) + 10}.{i % 100:02d}")
        for i in range(24)
    ]
    return _INVOICE.format(id=seed, customer=f"customer-{seed % 50}", lines="\n".join(lines))


def validate(xml: str) -> int:
    """Return the total in cents; raises if anything is malformed."""
    subtotal = Decimal("0")
    for qty, unit in _AMOUNT.findall(xml):
        try:
            subtotal += Decimal(unit) * int(qty)
        except InvalidOperation as exc:  # pragma: no cover - generated input is valid
            raise ValueError(f"bad amount {unit!r}") from exc
    rate = Decimal(_TAX.search(xml).group(1))
    total = subtotal * (1 + rate)
    return int(total * 100)


BATCH = 120


def run(seed: int) -> int:
    """One task = one batch of BATCH invoices, ~20 ms of interpreter work."""
    start = seed * BATCH
    return sum(validate(_make_invoice(n)) for n in range(start, start + BATCH))


if __name__ == "__main__":
    print(run(1))
