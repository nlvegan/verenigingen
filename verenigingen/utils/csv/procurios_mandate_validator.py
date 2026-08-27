# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""CSV-shape validation and row mapping for the Procurios SEPA mandate export.

Pure Python: no DB access. Per-row business rules (member match,
duplicate detection, member conflict) live in the import controller,
which has DB state and pre-built caches.

Design: docs/plans/2026-05-27-procurios-mandate-import-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from frappe.utils import getdate

CANCELLED_CUTOFF_MONTHS = 12

REQUIRED_COLUMNS = [
    "Mandaatnummer",
    "IBAN",
    "Rekeninghouder",
    "Debiteur ID",
    "Datum van ondertekening",
]

MANDATE_TYPE_MAP = {
    "doorlopend": "RCUR",
    "eenmalig": "OOFF",
}


@dataclass
class ProcuriosMandateRow:
    """A single Procurios CSV row mapped to SEPA Mandate domain fields.

    `cancelled_date` is ISO `YYYY-MM-DD` or None. `is_cancelled` is a
    convenience flag so the controller can branch without re-parsing.
    `notes` is composed traceability text destined for SEPA Mandate.notes.
    """

    row_number: int
    mandate_id: str
    iban: str
    account_holder_name: str
    debiteur_id: str
    debiteur_naam: str
    sign_date: str
    cancelled_date: Optional[str]
    mandate_type: str
    notes: str

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_date is not None


class ProcuriosMandateValidator:
    """Maps Procurios SEPA mandate CSV rows to ProcuriosMandateRow objects."""

    def __init__(
        self,
        cutoff_months: int = CANCELLED_CUTOFF_MONTHS,
        today: Optional[date] = None,
    ):
        self.cutoff_months = cutoff_months
        # Default to frappe's site-tz today, not Python's date.today() (server/process
        # tz): in the late-UTC window the two name different calendar days, which moves
        # the cancelled-mandate cutoff by a day (#628). Callers may still inject one.
        self._today = today or getdate()

    # ---- public API ---------------------------------------------------

    def check_required_columns(self, headers: List[str]) -> List[str]:
        """Return the list of required columns missing from headers."""
        present = set(headers)
        return [c for c in REQUIRED_COLUMNS if c not in present]

    def validate_and_map(self, csv_data: List[Dict]) -> Tuple[List[ProcuriosMandateRow], List[str], int]:
        """Map every CSV row.

        Returns (mapped_rows, errors, filtered_old_cancelled_count).
        Rows that cancelled longer ago than the cutoff are dropped here
        and counted in `filtered_old_cancelled_count`. Per-row mapping
        errors are appended to `errors` and the bad row is skipped — they
        never abort the batch.
        """
        mapped: List[ProcuriosMandateRow] = []
        errors: List[str] = []
        filtered_old = 0

        for idx, row in enumerate(csv_data, start=1):
            try:
                m = self.map_row(row, row_num=idx)
            except ValueError as e:
                errors.append(str(e))
                continue

            if m.cancelled_date and self._is_too_old_cancelled(m.cancelled_date):
                filtered_old += 1
                continue

            mapped.append(m)

        return mapped, errors, filtered_old

    def map_row(self, row: Dict, row_num: int) -> ProcuriosMandateRow:
        """Map one CSV row. Raises ValueError on bad row (caller continues)."""
        # Required-field presence check
        for col in REQUIRED_COLUMNS:
            value = (row.get(col) or "").strip()
            if not value:
                raise ValueError(f"Row {row_num}: required column '{col}' is empty")

        sign_date = self._parse_date(row["Datum van ondertekening"], row_num, "Datum van ondertekening")
        opzeg = (row.get("Opzegdatum") or "").strip()
        cancelled_date = self._parse_date(opzeg, row_num, "Opzegdatum") if opzeg else None

        return ProcuriosMandateRow(
            row_number=row_num,
            mandate_id=row["Mandaatnummer"].strip(),
            iban=row["IBAN"].strip().upper(),
            account_holder_name=row["Rekeninghouder"].strip(),
            debiteur_id=row["Debiteur ID"].strip(),
            debiteur_naam=(row.get("Debiteur naam") or "").strip(),
            sign_date=sign_date,
            cancelled_date=cancelled_date,
            mandate_type=self._map_mandate_type(row.get("Type machtiging", "")),
            notes=self._compose_notes(row),
        )

    # ---- helpers ------------------------------------------------------

    def _is_too_old_cancelled(self, cancelled_iso: str) -> bool:
        """True if `cancelled_iso` is more than `cutoff_months` before today.

        Uses calendar-month math via `dateutil.relativedelta` rather than
        the previous 30-day-window approximation. The old `months * 30`
        approximation rejected cancellations between 360 and 365 days
        ago that, by calendar months, were still within the cutoff
        window (e.g. an exactly-12-months-old cancellation would be
        treated as "too old" because 360 < 365). Calendar-month math
        gives the contract its claimed semantics.
        """
        cancelled = date.fromisoformat(cancelled_iso)
        cutoff_threshold = self._today - relativedelta(months=self.cutoff_months)
        return cancelled < cutoff_threshold

    def _map_mandate_type(self, type_text: str) -> str:
        return MANDATE_TYPE_MAP.get((type_text or "").strip().lower(), "RCUR")

    def _parse_date(self, value: str, row_num: int, field: str) -> str:
        """Parse a Procurios date (YYYY-MM-DD). Raises ValueError on bad input."""
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Row {row_num}: invalid {field} '{value}': {e}") from e

    def _compose_notes(self, row: Dict) -> str:
        """Compose traceability text for SEPA Mandate.notes."""
        parts = ["Imported from Procurios."]
        if row.get("Incasso-afspraak ID"):
            parts.append(f"Incasso-afspraak ID {row['Incasso-afspraak ID']}.")
        if row.get("Administratie"):
            parts.append(f"Administratie: {row['Administratie']}.")
        if (row.get("Pre-notificatie datum") or "").strip():
            parts.append(f"Pre-notificatie datum: {row['Pre-notificatie datum']}.")
        return " ".join(parts)
