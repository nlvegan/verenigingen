"""#2127: a door offers payment plans, and the plan's template decides the amount rules.

Everything goes through the real guest endpoint (submit_short_application as Guest) and the real page
context. Fixtures build templates with a write after insert (validate rewrites the minimum from the
type); that write stands in for an admin editing the template in the Desk.
"""

import json
import re
import secrets

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api import short_application as sa
from verenigingen.services.member.application.door_plans import find_plan, offered_plans
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.query_counter import count_queries

IBAN = "NL91ABNA0417164300"
SUBMISSION = "Membership Application Submission"
PLAN_REFUSAL = "This payment plan is not available."


class DoorPlanCase(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        self.email = f"plan.{frappe.generate_hash(length=8).lower()}@example.org"
        self._previous_user = frappe.session.user
        self._previous_request = getattr(frappe.local, "request", None)
        self._previous_ip = getattr(frappe.local, "request_ip", None)

    def tearDown(self):
        frappe.local.request = self._previous_request
        frappe.local.request_ip = self._previous_ip
        frappe.set_user(self._previous_user)
        super().tearDown()

    def _plan_door(self, *plans, **fields):
        """A door with one plan row per (template, extra row fields); the first is the default unless a
        row says otherwise."""
        rows = []
        for index, (template, extra) in enumerate(plans):
            rows.append({"dues_template": template, "is_default": int(index == 0)} | extra)
        return self._door(plans=rows, **fields)

    def _type_minimum(self, minimum, default_rate):
        """A membership type minimum with a default template whose rate respects it (the configuration
        approval accepts: a default template below the type minimum is refused there)."""
        frappe.db.set_value("Membership Type", self.membership_type.name, "minimum_amount", minimum)
        type_template = frappe.db.get_value(
            "Membership Type", self.membership_type.name, "dues_schedule_template"
        )
        frappe.db.set_value(
            "Membership Dues Schedule", type_template, {"dues_rate": default_rate, "suggested_amount": default_rate}
        )

    def _plan_id(self, door, template):
        return next(row.name for row in door.plans if row.dues_template == template)

    def _guest_form(self, **overrides):
        data = {
            "first_name": "Anna",
            "last_name": "Berg",
            "email": self.email,
            "address_line1": "Kerkstraat",
            "postal_code": "1234AB",
            "house_number": "12",
            "city": "Utrecht",
            "country": "Netherlands",
            "amount": "12",
            "magazine_delivery": "Geen",
            "starter_guide_delivery": "Geen",
            "iban": IBAN,
            "bank_account_name": "A. Berg",
            "consent": "1",
            "leave_this_empty": "",
        }
        data.update(overrides)
        return data

    def _submit_plan_form(self, door_name, **overrides):
        """As Guest through the endpoint; (response, message_log, new Error Log rows). Each call is a new
        applicant unless it names an email: an address gets at most 3 confirmation mails a day."""
        if "email" not in overrides:
            self.email = f"plan.{frappe.generate_hash(length=8).lower()}@example.org"
        errors = frappe.db.count("Error Log")
        # The guest limiters key on the client IP, and their counters outlive a run.
        frappe.local.request_ip = f"10.{secrets.randbelow(256)}.{secrets.randbelow(256)}.{1 + secrets.randbelow(254)}"
        frappe.local.message_log = []
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application(door_name, **self._guest_form(**overrides))
        finally:
            frappe.set_user(self._previous_user)
        for name in frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name"):
            self.track_doc(SUBMISSION, name)
        return response, list(frappe.local.message_log), frappe.db.count("Error Log") - errors

    def _accepted(self, door, template, amount, **overrides):
        response, _log, _errors = self._submit_plan_form(
            door.name, plan=self._plan_id(door, template), amount=str(amount), **overrides
        )
        return response["success"]

    def _staged_payload(self):
        names = frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name", order_by="creation desc")
        return json.loads(frappe.db.get_value(SUBMISSION, names[0], "payload"))


class TestPlansOfferedAndSubmitted(DoorPlanCase):
    def test_a_quarterly_plan_is_offered_and_staged_with_its_own_frequency(self):
        quarterly = self._plan_template("Quarterly", mode="Fixed", dues_rate=30, minimum_amount=0)
        door = self._plan_door((quarterly, {}))
        [offered] = offered_plans(door)
        self.assertEqual((offered["frequency"], offered["mode"], offered["amount"]), ("Quarterly", "Fixed", 30))

        response, _log, _errors = self._submit_plan_form(door.name, plan=offered["id"], amount="30")

        self.assertTrue(response["success"], response)
        payload = self._staged_payload()
        self.assertEqual(payload["frequency"], "Quarterly")
        self.assertEqual(payload["selected_dues_schedule"], quarterly)
        self.assertEqual(payload["plan"], offered["id"])
        self.assertEqual(payload["amount"], 30)

    def test_each_plan_stages_its_own_template(self):
        monthly = self._plan_template("Monthly")
        semi = self._plan_template("Semi-Annual")
        door = self._plan_door((monthly, {}), (semi, {}))
        for template, frequency in ((monthly, "Monthly"), (semi, "Semi-Annual")):
            with self.subTest(frequency):
                self.assertTrue(self._accepted(door, template, 12))
                payload = self._staged_payload()
                self.assertEqual((payload["frequency"], payload["selected_dues_schedule"]), (frequency, template))

    def test_a_form_that_names_only_a_frequency_picks_the_one_plan_billed_that_way(self):
        """A page loaded before plans existed posts `frequency`. Only an unambiguous match is honoured."""
        monthly = self._plan_template("Monthly")
        quarterly = self._plan_template("Quarterly")
        second_monthly = self._plan_template("Monthly")
        door = self._plan_door((monthly, {}), (quarterly, {}))
        self.assertEqual(find_plan(door, None, "Quarterly")["template"], quarterly)
        self.assertIsNone(find_plan(door, None, "Annual"), "no plan billed yearly")
        ambiguous = self._plan_door((monthly, {}), (second_monthly, {}))
        self.assertIsNone(find_plan(ambiguous, None, "Monthly"), "two plans billed monthly: refuse, never pick one")
        self.assertIsNone(find_plan(door, None, None))

    def test_a_plan_whose_template_cannot_be_offered_is_left_out(self):
        monthly = self._plan_template("Monthly")
        quarterly = self._plan_template("Quarterly")
        door = self._plan_door((monthly, {}), (quarterly, {}))
        frappe.db.set_value("Membership Dues Schedule", quarterly, "status", "Cancelled")
        self.assertEqual([plan["template"] for plan in offered_plans(door)], [monthly])
        response, _log, _errors = self._submit_plan_form(door.name, plan=self._plan_id(door, quarterly))
        self.assertEqual(response, {"success": False, "message": PLAN_REFUSAL})


class TestAmountRulesPerContributionMode(DoorPlanCase):
    def test_fixed_means_exactly_the_template_amount(self):
        template = self._plan_template("Quarterly", mode="Fixed", dues_rate=30, minimum_amount=0)
        door = self._plan_door((template, {}))
        for amount in (29.99, 30.5, 300, 12):
            with self.subTest(amount=amount):
                self.assertFalse(self._accepted(door, template, amount))
        self.assertTrue(self._accepted(door, template, 30))  # control: the template amount passes
        self.assertTrue(self._accepted(door, template, "30,00"))

    def test_fixed_with_paper_delivery_charges_exactly_the_postal_minimum_when_it_is_higher(self):
        """Ruling on #2127: paper charges max(rate, postal minimum); digital charges the rate."""
        template = self._plan_template("Monthly", mode="Fixed", dues_rate=15, minimum_amount=0)
        door = self._plan_door((template, {"postal_minimum": 30}))
        for delivery in ("Papier", "Beide"):
            with self.subTest(delivery):
                self.assertTrue(self._accepted(door, template, 30, magazine_delivery=delivery))
                self.assertFalse(self._accepted(door, template, 15, magazine_delivery=delivery))
                self.assertFalse(self._accepted(door, template, 45, magazine_delivery=delivery))
        self.assertTrue(self._accepted(door, template, 15), "digital: the rate")
        self.assertFalse(self._accepted(door, template, 30), "digital: not the paper price")
        [plan] = offered_plans(door)
        self.assertEqual((plan["amount"], plan["postal_minimum"]), (15, 30))

    def test_fixed_with_a_postal_minimum_below_the_rate_charges_the_rate_on_paper(self):
        template = self._plan_template("Monthly", mode="Fixed", dues_rate=15, minimum_amount=0)
        door = self._plan_door((template, {"postal_minimum": 10}))
        self.assertTrue(self._accepted(door, template, 15, magazine_delivery="Papier"))
        self.assertFalse(self._accepted(door, template, 10, magazine_delivery="Papier"))

    def test_income_based_paper_delivery_raises_the_floor_to_the_postal_minimum(self):
        template = self._plan_template("Monthly", mode="Income-Based", minimum_amount=5)
        door = self._plan_door((template, {"postal_minimum": 20}))
        self.assertFalse(self._accepted(door, template, 19.99, magazine_delivery="Papier"))
        self.assertTrue(self._accepted(door, template, 20, magazine_delivery="Papier"))
        self.assertTrue(self._accepted(door, template, 5), "digital: the template minimum")

    def test_the_floor_is_the_one_approval_applies_not_just_the_plan_templates(self):
        """Approval validates the schedule against max(the type's default template minimum, the
        membership type minimum). A plan template with a lower minimum must not let a submit through
        that approval would then refuse (and swallow, leaving no schedule)."""
        self._type_minimum(25, default_rate=30)
        template = self._plan_template("Monthly", suggested_amount=30, allow_custom_amount=1, minimum_amount=5)
        door = self._plan_door((template, {}))
        [plan] = offered_plans(door)
        self.assertEqual(plan["minimum"], 25)
        self.assertFalse(self._accepted(door, template, 12))
        self.assertFalse(self._accepted(door, template, 24.99))
        self.assertTrue(self._accepted(door, template, 25))

    def test_a_fixed_plan_below_the_floor_approval_applies_is_not_offered(self):
        self._type_minimum(25, default_rate=30)
        template = self._plan_template("Monthly", mode="Fixed", dues_rate=15, minimum_amount=0)
        door = self._plan_door((template, {}))
        self.assertEqual(offered_plans(door), [])
        # Control: a Fixed plan at or above the floor is offered.
        ok = self._plan_template("Monthly", mode="Fixed", dues_rate=25, minimum_amount=0)
        self.assertEqual([p["template"] for p in offered_plans(self._plan_door((ok, {})))], [ok])

    def test_nothing_is_offered_when_approval_itself_would_refuse_the_type(self):
        """A type whose default template is below its own minimum cannot get a schedule at approval
        (the template service refuses), so no plan of that type is offered: fail closed."""
        frappe.db.set_value("Membership Type", self.membership_type.name, "minimum_amount", 25)
        template = self._plan_template("Monthly", suggested_amount=30, minimum_amount=5)
        self.assertEqual(offered_plans(self._plan_door((template, {}))), [])

    def test_flexible_without_custom_amounts_takes_suggested_and_presets_only(self):
        template = self._plan_template("Monthly", suggested_amount=15, allow_custom_amount=0)
        door = self._door(
            plans=[{"dues_template": template, "is_default": 1}],
            amount_options=[{"dues_template": template, "amount": 25}],
        )
        self.assertTrue(self._accepted(door, template, 15), "the suggested amount")
        self.assertTrue(self._accepted(door, template, 25), "a preset of this plan")
        for amount in (16, 24.99, 100):
            with self.subTest(custom=amount):
                self.assertFalse(self._accepted(door, template, amount))

    def test_flexible_with_custom_amounts_takes_any_amount_from_the_minimum(self):
        template = self._plan_template("Monthly", suggested_amount=15, allow_custom_amount=1, minimum_amount=4)
        door = self._plan_door((template, {}))
        self.assertTrue(self._accepted(door, template, 4), "a custom amount at the minimum")
        self.assertTrue(self._accepted(door, template, 99))
        self.assertFalse(self._accepted(door, template, 3.99), "below the minimum")

    def test_a_preset_belongs_to_its_own_plan(self):
        monthly = self._plan_template("Monthly", suggested_amount=15, allow_custom_amount=0)
        quarterly = self._plan_template("Quarterly", suggested_amount=40, allow_custom_amount=0)
        door = self._door(
            plans=[{"dues_template": monthly, "is_default": 1}, {"dues_template": quarterly}],
            amount_options=[{"dues_template": quarterly, "amount": 60}],
        )
        self.assertTrue(self._accepted(door, quarterly, 60))
        self.assertFalse(self._accepted(door, monthly, 60), "the Quarterly preset is not a Monthly amount")

    def test_income_based_takes_any_amount_from_the_minimum_whatever_the_custom_flag(self):
        template = self._plan_template(
            "Quarterly", mode="Income-Based", minimum_amount=9, allow_custom_amount=0, income_percentage=1.5
        )
        door = self._plan_door((template, {}))
        self.assertFalse(self._accepted(door, template, 8.99))
        self.assertTrue(self._accepted(door, template, 9))
        self.assertTrue(self._accepted(door, template, 33.37), "a calculated amount is an arbitrary figure")

    def test_postal_minimum_is_per_plan(self):
        monthly = self._plan_template("Monthly", minimum_amount=2.5)
        quarterly = self._plan_template("Quarterly", minimum_amount=2.5)
        door = self._plan_door((monthly, {"postal_minimum": 5}), (quarterly, {"postal_minimum": 20}))
        for template, postal, amount, ok in (
            (monthly, "Papier", 5, True),
            (monthly, "Papier", 4.99, False),
            (quarterly, "Papier", 5, False),
            (quarterly, "Beide", 20, True),
            (quarterly, "Geen", 5, True),
            (monthly, "Geen", 2.5, True),
        ):
            with self.subTest(template=template, postal=postal, amount=amount):
                self.assertEqual(self._accepted(door, template, amount, magazine_delivery=postal), ok)

    def test_a_postal_minimum_below_the_template_minimum_never_lowers_it(self):
        template = self._plan_template("Monthly", minimum_amount=6)
        door = self._plan_door((template, {"postal_minimum": 1}))
        self.assertFalse(self._accepted(door, template, 5, magazine_delivery="Papier"))
        self.assertFalse(self._accepted(door, template, 5))


class TestPlanRefusalsAreIdentical(DoorPlanCase):
    def _refusal_channels(self, door_name, **overrides):
        """Every channel a guest can read from a refusal."""
        with count_queries() as counter:
            response, log, errors = self._submit_plan_form(door_name, email=self.email, **overrides)
        return {
            "queries": len(counter.queries),
            "response": response,
            "message_log": log,
            "error_log_rows": errors,
            "submissions": frappe.db.count(SUBMISSION, {"email": self.email}),
        }

    def test_another_doors_plan_an_unknown_plan_and_junk_are_refused_alike(self):
        mine = self._plan_template("Monthly")
        theirs = self._plan_template("Quarterly")
        door = self._plan_door((mine, {}))
        other_door = self._plan_door((theirs, {}))
        foreign = self._plan_id(other_door, theirs)
        self.assertTrue(
            frappe.db.exists("Membership Application Door Plan", foreign),  # doctype-ok: new in #2127
            "control: it exists",
        )
        self._refusal_channels(door.name, plan="warm-the-caches", amount="12")  # a cold first call counts extra
        unknown = self._refusal_channels(door.name, plan="does-not-exist", amount="12")
        for label, plan in (
            ("another door's plan", foreign),
            ("another door's template name", theirs),
            ("a list", ["x"]),
            ("a dict", {"a": 1}),
        ):
            with self.subTest(label):
                refused = self._refusal_channels(door.name, plan=plan, amount="12")
                self.assertEqual(refused, unknown)
        self.assertEqual(unknown["response"], {"success": False, "message": PLAN_REFUSAL})
        self.assertEqual(unknown["submissions"], 0)
        self.assertTrue(self._accepted(door, mine, 12), "control: this door's own plan is accepted")

    def test_a_plan_of_a_disabled_or_unknown_door_gets_the_same_answer_as_an_unknown_door(self):
        template = self._plan_template("Monthly")
        disabled = self._plan_door((template, {}), enabled=0)
        plan = self._plan_id(disabled, template)
        unknown_door = self._refusal_channels("bestaat-niet", plan=plan, amount="12")
        self.assertEqual(self._refusal_channels(disabled.name, plan=plan, amount="12"), unknown_door)


class TestWordLidPlanPage(DoorPlanCase):
    def setUp(self):
        super().setUp()
        frappe.cache.delete_value("website_route_rules")

    def tearDown(self):
        frappe.form_dict.pop("door", None)
        super().tearDown()

    def _door_page_context(self, door):
        from verenigingen.www import word_lid

        frappe.form_dict.pop("door", None)
        frappe.form_dict["door"] = door.name
        return word_lid.get_context(frappe._dict())

    def _door_page_html(self, door):
        from frappe.website.serve import get_response

        path = f"word-lid/{door.slug}"
        frappe.local.request = Request(EnvironBuilder(path=f"/{path}").get_environ())
        frappe.set_user("Guest")
        try:
            response = get_response(path)
        finally:
            frappe.set_user(self._previous_user)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_the_default_plan_is_preselected_and_the_others_can_be_chosen(self):
        monthly = self._plan_template("Monthly")
        quarterly = self._plan_template("Quarterly")
        annual = self._plan_template("Annual")
        door = self._door(
            plans=[
                {"dues_template": monthly},
                {"dues_template": quarterly, "is_default": 1, "label": "Per kwartaal"},
                {"dues_template": annual},
            ]
        )
        context = self._door_page_context(door)
        default_id = self._plan_id(door, quarterly)
        self.assertEqual(context.default_plan_id, default_id)
        self.assertEqual(len(context.plans), 3)
        html = self._door_page_html(door)
        checked = re.findall(r'<input type="radio" name="plan_choice" value="([^"]+)" checked>', html)
        self.assertEqual(checked, [default_id], "only the default plan is preselected")
        for template in (monthly, annual):
            self.assertIn(f'name="plan_choice" value="{self._plan_id(door, template)}"', html)
        self.assertIn('name="plan" id="wl-plan" value="%s"' % default_id, html)
        self.assertIn("Per kwartaal", html)
        # A non-default plan can be chosen and is what gets staged.
        self.assertTrue(self._accepted(door, annual, 12))
        self.assertEqual(self._staged_payload()["selected_dues_schedule"], annual)

    def test_a_single_plan_has_no_picker_but_is_preselected(self):
        template = self._plan_template("Quarterly")
        door = self._plan_door((template, {}))
        html = self._door_page_html(door)
        self.assertNotIn('name="plan_choice"', html)
        self.assertIn('name="plan" id="wl-plan" value="%s"' % self._plan_id(door, template), html)

    def test_the_page_carries_each_plans_amount_rules(self):
        fixed = self._plan_template("Monthly", mode="Fixed", dues_rate=30, minimum_amount=0)
        flexible = self._plan_template("Quarterly", suggested_amount=40, allow_custom_amount=0)
        door = self._door(
            plans=[{"dues_template": fixed, "is_default": 1}, {"dues_template": flexible, "postal_minimum": 50}],
            amount_options=[{"dues_template": flexible, "amount": 60}],
        )
        plans = {plan["template"]: plan for plan in self._door_page_context(door).plans}
        self.assertEqual(
            (plans[fixed]["mode"], plans[fixed]["amount"], plans[fixed]["presets"]), ("Fixed", 30, [])
        )
        self.assertEqual(plans[flexible]["mode"], "Flexible")
        self.assertEqual(plans[flexible]["suggested"], 40)
        self.assertEqual(plans[flexible]["presets"], [60])
        self.assertFalse(plans[flexible]["allow_custom"])
        self.assertEqual(plans[flexible]["postal_minimum"], 50)
        self.assertEqual(plans[flexible]["frequency"], "Quarterly")

    def test_income_based_plan_renders_the_calculator_and_its_settings(self):
        template = self._plan_template(
            "Quarterly", mode="Income-Based", income_calculation_type="Percentage", income_percentage=1.25
        )
        door = self._plan_door((template, {}))
        [plan] = self._door_page_context(door).plans
        self.assertEqual(plan["mode"], "Income-Based")
        self.assertEqual(plan["calculator"]["calculation_type"], "Percentage")
        self.assertEqual(plan["calculator"]["percentage"], 1.25)
        html = self._door_page_html(door)
        self.assertIn('id="income-calculator"', html, "the full form's calculator markup is reused")
        self.assertIn('id="calc-monthly-income"', html)
        carried = json.loads(re.search(r"data-plans='([^']*)'", html).group(1))
        self.assertEqual(carried[0]["calculator"]["percentage"], 1.25)

    def test_the_page_never_shows_template_placeholders(self):
        template = self._plan_template("Quarterly", mode="Income-Based")
        html = self._door_page_html(self._plan_door((template, {})))
        self.assertNotIn("{{", html)
        self.assertNotIn("calculator_description", html)
        self.assertNotIn("income_percentage_rate", html)

    def test_a_door_with_no_offerable_plan_says_so_instead_of_an_empty_amount_block(self):
        template = self._plan_template("Monthly")
        door = self._plan_door((template, {}))
        frappe.db.set_value("Membership Dues Schedule", template, "status", "Cancelled")
        html = self._door_page_html(door)
        self.assertIn("This form cannot be used right now", html)
        self.assertNotIn('id="wl-amount-block"', html)
        # Control: a door with an offerable plan shows the amount block and no such message.
        ok = self._door_page_html(self._plan_door((self._plan_template("Monthly"), {})))
        self.assertIn('id="wl-amount-block"', ok)
        self.assertNotIn("This form cannot be used right now", ok)
