# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""CSV-shape validation + row mapping for the Procurios membership export.

Pure Python, no DB access — mirrors procurios_mandate_validator.py. Per-row
business rules (member match, dedup, active-conflict) live in the controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from frappe.utils import getdate

REQUIRED_COLUMNS = ["Debiteur Id", "Type", "Ingangsdatum", "Id"]


@dataclass
class ProcuriosMembershipRow:
    row_number: int
    debiteur_id: str
    debiteur_naam: str
    procurios_type: str
    payment_period: str
    start_date: str
    dues_rate: Optional[float]
    procurios_membership_id: str
    status: str  # Active | Cancelled | Expired
    cancellation_date: Optional[str]


class ProcuriosMembershipValidator:
    def __init__(self, today: Optional[date] = None):
        # Default to frappe's site-tz today, not Python's date.today() (server/process
        # tz): in the late-UTC window the two name different calendar days, which flips
        # a membership ending today between Expired and Active, and stamps a
        # cancellation date a day off (#628). Callers may still inject one.
        self._today = today or getdate()

    def check_required_columns(self, headers: List[str]) -> List[str]:
        present = set(headers)
        return [c for c in REQUIRED_COLUMNS if c not in present]

    def extract_membership_types(self, csv_data: List[Dict]) -> List[str]:
        seen = {(row.get("Type") or "").strip() for row in csv_data}
        return sorted(t for t in seen if t)

    def validate_and_map(self, csv_data: List[Dict]) -> Tuple[List[ProcuriosMembershipRow], List[str]]:
        mapped: List[ProcuriosMembershipRow] = []
        errors: List[str] = []
        for idx, row in enumerate(csv_data, start=2):  # +1 header, 1-indexed
            try:
                mapped.append(self.map_row(row, idx))
            except ValueError as e:
                errors.append(str(e))
        return mapped, errors

    def map_row(self, row: Dict, row_num: int) -> ProcuriosMembershipRow:
        for col in REQUIRED_COLUMNS:
            if not (row.get(col) or "").strip():
                raise ValueError(f"Row {row_num}: required column '{col}' is empty")

        start_date = self._parse_date(row["Ingangsdatum"], row_num, "Ingangsdatum")
        opgezegd = (row.get("Opgezegd") or "").strip()
        einddatum = (row.get("Einddatum") or "").strip()

        status, cancellation_date = self._determine_status(opgezegd, einddatum)

        return ProcuriosMembershipRow(
            row_number=row_num,
            debiteur_id=row["Debiteur Id"].strip(),
            debiteur_naam=(row.get("Debiteur Naam") or "").strip(),
            procurios_type=row["Type"].strip(),
            payment_period=self._map_payment_period(row.get("Looptijd", "")),
            start_date=start_date,
            dues_rate=self._parse_rate(row),
            procurios_membership_id=row["Id"].strip(),
            status=status,
            cancellation_date=cancellation_date,
        )

    # ---- helpers ----

    def _determine_status(self, opgezegd: str, einddatum: str) -> Tuple[str, Optional[str]]:
        if opgezegd:
            cancelled = self._try_parse(opgezegd) or self._try_parse(einddatum) or self._today.isoformat()
            return "Cancelled", cancelled
        if einddatum:
            end = self._try_parse(einddatum)
            if end and date.fromisoformat(end) < self._today:
                return "Expired", end
        return "Active", None

    def _map_payment_period(self, looptijd: str) -> str:
        t = (looptijd or "").strip().lower()
        if "maand" in t:
            return "Maandelijks"
        if "kwartaal" in t:
            return "Kwartaal"
        if "jaar" in t:
            return "Jaarlijks"
        return ""

    def _parse_rate(self, row: Dict) -> Optional[float]:
        for col in ("Normale prijs (type)", "Normale prijs (abonnement)"):
            raw = (row.get(col) or "").strip().replace(",", ".")
            if raw:
                try:
                    return float(raw)
                except ValueError:
                    continue
        return None

    def _parse_date(self, value: str, row_num: int, field: str) -> str:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Row {row_num}: invalid {field} '{value}': {e}") from e

    def _try_parse(self, value: str) -> Optional[str]:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
        except (ValueError, AttributeError):
            return None
