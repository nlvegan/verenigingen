"""Server-side validation of the short membership application form."""

import frappe
from frappe.utils import getdate, nowdate

from verenigingen.services.member.application import short_application_validation as sav
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase

SHAPE_PAYER_IBAN = "NL91ABNA0417164300"


class TestShortApplicationValidation(ApplicationDoorMixin, VereningingenUnitTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        self.template_minimum = 2.5
        self.postal_minimum = 5.0
        # The auto-made template is Annual; the door's monthly slot takes only a Monthly one.
        frappe.db.set_value(
            "Membership Dues Schedule",
            template,
            {"minimum_amount": self.template_minimum, "billing_frequency": "Monthly"},
        )
        self.template = template
        self.door = self._door(
            monthly_dues_template=template, postal_minimum_monthly=self.postal_minimum
        )
        self.housemate_door = self._door(form_shape="Housemate", monthly_dues_template=None)
        self.reason = self._master("Membership Join Reason", "reason")
        self.source = self._master("Membership Referral Source", "source")

    def _master(self, doctype, field, enabled=1):
        doc = frappe.get_doc(
            {"doctype": doctype, field: f"Test {frappe.generate_hash(length=8)}", "enabled": enabled}
        ).insert()
        self.track_doc(doctype, doc.name)
        return doc.name

    def _validation_data(self, **overrides):
        data = {
            "first_name": "  Anna ",
            "tussenvoegsel": "van",
            "last_name": "Berg",
            "email": " Anna@Example.ORG ",
            "mobile_no": "+31612345678",
            "address_line1": "Kerkstraat",
            "postal_code": "1234AB",
            "house_number": "12",
            "house_number_addition": "A",
            "city": "Utrecht",
            "country": "Netherlands",
            "frequency": "Monthly",
            "amount": "7.50",
            "magazine_delivery": "Digitaal",
            "starter_guide_delivery": "Geen",
            "iban": SHAPE_PAYER_IBAN,
            "bank_account_name": "A. van Berg",
            "consent": "1",
            "birth_year": "1990",
            "join_reasons": [self.reason],
            "referral_source": self.source,
            "website": "",
        }
        data.update(overrides)
        return data

    def _housemate_data(self, **overrides):
        data = self._validation_data(
            housemate_of_name="Piet Payer", housemate_confirmed="1", amount="", iban="", consent=""
        )
        data.update(overrides)
        return data

    def test_valid_regular_payload_is_cleaned(self):
        cleaned = sav.validate_short_application(self.door, self._validation_data())
        self.assertEqual(cleaned["selected_dues_schedule"], self.door.monthly_dues_template)
        self.assertEqual(cleaned["email"], "anna@example.org")
        self.assertEqual(cleaned["first_name"], "Anna")
        self.assertEqual(cleaned["amount"], 7.5)
        self.assertEqual(cleaned["frequency"], "Monthly")
        self.assertEqual(cleaned["consent_text_version"], sav.CONSENT_TEXT_VERSION)
        self.assertTrue(cleaned["consent_given_at"])
        self.assertEqual(cleaned["join_reasons"], [self.reason])
        self.assertEqual(cleaned["referral_source"], self.source)
        self.assertEqual(cleaned["birth_year"], 1990)
        self.assertNotIn("website", cleaned)

    def test_monthly_without_iban_refused(self):
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(iban=""))

    def test_invalid_iban_refused(self):
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(iban="NL00BOGUS0000000000"))

    def test_amount_below_template_minimum_refused(self):
        amount = self.template_minimum - 0.01
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(amount=str(amount)))
        # Exactly the minimum is accepted.
        cleaned = sav.validate_short_application(self.door, self._validation_data(amount=str(self.template_minimum)))
        self.assertEqual(cleaned["amount"], self.template_minimum)

    def test_amount_below_postal_minimum_refused_when_papier(self):
        amount = (self.template_minimum + self.postal_minimum) / 2
        self.assertGreaterEqual(amount, self.template_minimum)
        self.assertLess(amount, self.postal_minimum)
        for kwargs in (
            {"magazine_delivery": "Papier"},
            {"starter_guide_delivery": "Beide"},
        ):
            with self.assertRaises(frappe.ValidationError):
                sav.validate_short_application(self.door, self._validation_data(amount=str(amount), **kwargs))
        cleaned = sav.validate_short_application(
            self.door, self._validation_data(amount=str(amount), magazine_delivery="Digitaal")
        )
        self.assertEqual(cleaned["amount"], amount)
        cleaned = sav.validate_short_application(
            self.door, self._validation_data(amount=str(self.postal_minimum), magazine_delivery="Papier")
        )
        self.assertEqual(cleaned["amount"], self.postal_minimum)

    def test_hidden_delivery_question_counts_as_not_postal(self):
        door = self._door(
            monthly_dues_template=self.template,
            postal_minimum_monthly=self.postal_minimum,
            hidden_questions=[{"question": "magazine_delivery"}, {"question": "starter_guide_delivery"}],
        )
        amount = (self.template_minimum + self.postal_minimum) / 2
        cleaned = sav.validate_short_application(
            door, self._validation_data(amount=str(amount), magazine_delivery="Papier", country="Belgium")
        )
        self.assertNotIn("magazine_delivery", cleaned)
        self.assertNotIn("starter_guide_delivery", cleaned)

    def test_papier_refused_for_non_nl_address(self):
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(
                self.door, self._validation_data(country="Belgium", starter_guide_delivery="Beide")
            )
        cleaned = sav.validate_short_application(self.door, self._validation_data(country="Belgium"))
        self.assertEqual(cleaned["country"], "Belgium")

    def test_frequency_without_door_template_refused(self):
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(frequency="Annual", iban=""))

    def test_missing_required_field_refused(self):
        for field in ("first_name", "last_name", "email", "address_line1", "postal_code", "city", "country"):
            with self.subTest(field=field):
                for blank in ("", "   ", None):
                    with self.assertRaises(frappe.ValidationError):
                        sav.validate_short_application(self.door, self._validation_data(**{field: blank}))

    def test_invalid_email_refused(self):
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(email="not-an-email"))

    def test_regular_without_consent_refused(self):
        for value in ("", "0", 0, None, False):
            with self.assertRaises(frappe.ValidationError):
                sav.validate_short_application(self.door, self._validation_data(consent=value))

    def test_consent_accepts_form_truthy_values(self):
        for value in ("1", 1, True):
            sav.validate_short_application(self.door, self._validation_data(consent=value))

    def test_housemate_requires_payer_name_and_confirmation(self):
        cleaned = sav.validate_short_application(self.housemate_door, self._housemate_data())
        self.assertEqual(cleaned["housemate_of_name"], "Piet Payer")
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.housemate_door, self._housemate_data(housemate_of_name=" "))
        for value in ("", "0", None):
            with self.assertRaises(frappe.ValidationError):
                sav.validate_short_application(
                    self.housemate_door, self._housemate_data(housemate_confirmed=value)
                )

    def test_housemate_ignores_amount_and_iban(self):
        cleaned = sav.validate_short_application(
            self.housemate_door,
            self._housemate_data(amount="99", iban=SHAPE_PAYER_IBAN, frequency="Monthly", consent="1"),
        )
        for key in ("amount", "selected_dues_schedule", "iban", "frequency", "consent_given_at"):
            self.assertNotIn(key, cleaned)

    def test_regular_ignores_housemate_fields(self):
        cleaned = sav.validate_short_application(
            self.door, self._validation_data(housemate_of_name="X", housemate_confirmed="1")
        )
        self.assertNotIn("housemate_of_name", cleaned)

    def test_hidden_question_values_are_dropped(self):
        door = self._door(
            monthly_dues_template=self.template, hidden_questions=[{"question": "birth_year"}]
        )
        cleaned = sav.validate_short_application(door, self._validation_data(birth_year=1990))
        self.assertNotIn("birth_year", cleaned)
        # Control: a door that hides nothing keeps it.
        self.assertEqual(sav.validate_short_application(self.door, self._validation_data(birth_year=1990))["birth_year"], 1990)

    def test_hidden_question_is_not_validated(self):
        door = self._door(
            monthly_dues_template=self.template, hidden_questions=[{"question": "birth_year"}]
        )
        cleaned = sav.validate_short_application(door, self._validation_data(birth_year=1))
        self.assertNotIn("birth_year", cleaned)

    def test_dutch_decimal_comma_amount_accepted(self):
        self.assertEqual(sav.validate_short_application(self.door, self._validation_data(amount="7,50"))["amount"], 7.5)
        self.assertEqual(sav.validate_short_application(self.door, self._validation_data(amount="7.50"))["amount"], 7.5)

    def test_unparseable_amount_refused(self):
        for value in ("abc", "", None, "-3", "nan"):
            with self.assertRaises(frappe.ValidationError):
                sav.validate_short_application(self.door, self._validation_data(amount=value))

    def test_birth_year_out_of_range_refused(self):
        year = getdate(nowdate()).year
        for bad in (year + 1, year - 121, "abcd"):
            with self.assertRaises(frappe.ValidationError):
                sav.validate_short_application(self.door, self._validation_data(birth_year=bad))
        for good in (year, year - 120):
            self.assertEqual(
                sav.validate_short_application(self.door, self._validation_data(birth_year=good))["birth_year"], good
            )

    def test_more_than_five_reasons_refused(self):
        reasons = [self._master("Membership Join Reason", "reason") for _ in range(6)]
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(join_reasons=reasons))
        cleaned = sav.validate_short_application(self.door, self._validation_data(join_reasons=reasons[:5]))
        self.assertEqual(cleaned["join_reasons"], reasons[:5])

    def test_unknown_reason_or_source_refused(self):
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(join_reasons=["Bestaat niet"]))
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(referral_source="Bestaat niet"))
        disabled_reason = self._master("Membership Join Reason", "reason", enabled=0)
        disabled_source = self._master("Membership Referral Source", "source", enabled=0)
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(join_reasons=[disabled_reason]))
        with self.assertRaises(frappe.ValidationError):
            sav.validate_short_application(self.door, self._validation_data(referral_source=disabled_source))

    def test_optional_questions_may_be_empty(self):
        cleaned = sav.validate_short_application(
            self.door, self._validation_data(birth_year="", join_reasons=[], referral_source="", mobile_no="")
        )
        self.assertNotIn("birth_year", cleaned)
        self.assertEqual(cleaned["join_reasons"], [])
