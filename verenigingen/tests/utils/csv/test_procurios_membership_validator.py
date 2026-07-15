import unittest
from datetime import date

from verenigingen.utils.csv.procurios_membership_validator import (
    ProcuriosMembershipValidator,
)


class TestProcuriosMembershipValidator(unittest.TestCase):
    def setUp(self):
        self.v = ProcuriosMembershipValidator(today=date(2026, 7, 15))

    def _row(self, **over):
        base = {
            "Debiteur Id": "67017",
            "Debiteur Naam": "Amanda de Nijs",
            "Type": "Maandlid",
            "Looptijd": "1 Maand",
            "Ingangsdatum": "2022-11-27",
            "Opgezegd": "",
            "Einddatum": "",
            "Normale prijs (type)": "2.5",
            "Id": "7112",
        }
        base.update(over)
        return base

    def test_required_columns_missing(self):
        missing = self.v.check_required_columns(["Debiteur Id", "Type"])
        self.assertIn("Ingangsdatum", missing)
        self.assertIn("Id", missing)

    def test_active_row(self):
        rows, errors = self.v.validate_and_map([self._row()])
        self.assertEqual(errors, [])
        r = rows[0]
        self.assertEqual(r.debiteur_id, "67017")
        self.assertEqual(r.procurios_membership_id, "7112")
        self.assertEqual(r.status, "Active")
        self.assertEqual(r.payment_period, "Maandelijks")
        self.assertEqual(r.start_date, "2022-11-27")
        self.assertEqual(r.dues_rate, 2.5)
        self.assertIsNone(r.cancellation_date)

    def test_cancelled_row_sets_status_and_date(self):
        rows, _ = self.v.validate_and_map([self._row(Opgezegd="2023-05-01")])
        self.assertEqual(rows[0].status, "Cancelled")
        self.assertEqual(rows[0].cancellation_date, "2023-05-01")

    def test_expired_row_past_einddatum(self):
        rows, _ = self.v.validate_and_map([self._row(Einddatum="2024-01-01")])
        self.assertEqual(rows[0].status, "Expired")
        self.assertEqual(rows[0].cancellation_date, "2024-01-01")

    def test_jaarlid_payment_period(self):
        rows, _ = self.v.validate_and_map([self._row(Type="Jaarlid", Looptijd="1 Jaar")])
        self.assertEqual(rows[0].payment_period, "Jaarlijks")

    def test_duplicate_type_column_takes_membership_type(self):
        # csv.DictReader collapses duplicate headers; validator must read the
        # de-duplicated single "Type" value, not crash.
        rows, _ = self.v.validate_and_map([self._row(Type="Jaarlid")])
        self.assertEqual(rows[0].procurios_type, "Jaarlid")

    def test_extract_membership_types_distinct_sorted(self):
        data = [self._row(), self._row(Type="Jaarlid"), self._row(Type="Maandlid")]
        self.assertEqual(self.v.extract_membership_types(data), ["Jaarlid", "Maandlid"])

    def test_missing_required_value_is_row_error(self):
        rows, errors = self.v.validate_and_map([self._row(**{"Debiteur Id": ""})])
        self.assertEqual(rows, [])
        self.assertTrue(any("Debiteur Id" in e for e in errors))

    def test_comma_decimal_dues_rate(self):
        rows, _ = self.v.validate_and_map([self._row(**{"Normale prijs (type)": "2,5"})])
        self.assertEqual(rows[0].dues_rate, 2.5)

    def test_kwartaal_payment_period(self):
        rows, _ = self.v.validate_and_map([self._row(Type="Kwartaallid", Looptijd="1 Kwartaal")])
        self.assertEqual(rows[0].payment_period, "Kwartaal")

    def test_cancelled_cascade_falls_back_to_einddatum_then_today(self):
        rows, _ = self.v.validate_and_map([self._row(Opgezegd="ja", Einddatum="2023-05-01")])
        self.assertEqual(rows[0].status, "Cancelled")
        self.assertEqual(rows[0].cancellation_date, "2023-05-01")

        rows, _ = self.v.validate_and_map([self._row(Opgezegd="ja", Einddatum="")])
        self.assertEqual(rows[0].status, "Cancelled")
        self.assertEqual(rows[0].cancellation_date, "2026-07-15")

    def test_dues_rate_falls_back_to_abonnement_column(self):
        rows, _ = self.v.validate_and_map(
            [self._row(**{"Normale prijs (type)": "", "Normale prijs (abonnement)": "20"})]
        )
        self.assertEqual(rows[0].dues_rate, 20.0)
