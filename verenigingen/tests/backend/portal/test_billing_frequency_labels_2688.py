"""
#2688: portal pages must speak the real Membership Dues Schedule vocabulary.

- payment_dashboard "Current rate ... per X": Annual and Semi-Annual used to fall through
  to the raw option lowered, "per annual" / "per semi-annual".
- my_dues_schedule: Start Date, Auto-Renewal and Notification read fields the DocType does
  not have, so they always rendered blank / "Disabled"; the End Date cell could never show a
  date for an Active schedule. They are removed.

Probe shortcut (declared): the Active schedule comes from the real create_test_membership
flow; billing_frequency is then set with db.set_value. Pages are driven through the real
get_response_content.
"""

import frappe

from verenigingen.tests.backend.portal.test_page_portal_cluster import PortalPageTestBase

# (billing_frequency, label the member should read after "per")
LABELS = [
    ("Daily", "day"),
    ("Weekly", "week"),
    ("Monthly", "month"),
    ("Quarterly", "quarter"),
    ("Semi-Annual", "half year"),
    ("Annual", "year"),
]


class TestBillingFrequencyLabels2688(PortalPageTestBase):
    def _member_with_frequency(self, frequency):
        member, user = self._make_member_with_user()
        self.create_test_membership(member_name=member.name)
        schedule = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member.name, "status": "Active"}, pluck="name"
        )[0]
        frappe.db.set_value("Membership Dues Schedule", schedule, "billing_frequency", frequency)
        frappe.db.set_value("Member", member.name, "current_dues_schedule", schedule)
        return user

    def _render_label_page_2688(self, page, user):
        from frappe.website.serve import get_response_content

        with self.as_user(user):
            return get_response_content(page)

    def _label_span(self, label):
        return f'<span class="text-sm text-gray-500">{label}</span>'

    def _current_rate_line(self, html):
        start = html.index("Current rate")
        return html[start : html.index("</p>", start)]

    def test_payment_dashboard_rate_line_names_every_frequency(self):
        for frequency, label in LABELS:
            with self.subTest(frequency=frequency):
                user = self._member_with_frequency(frequency)
                line = self._current_rate_line(self._render_label_page_2688("payment_dashboard", user))
                text = " ".join(line.split())
                self.assertIn(f"</strong> per {label} <a", text)

    def test_my_dues_schedule_shows_no_fields_the_doctype_lacks(self):
        meta = frappe.get_meta("Membership Dues Schedule")
        for gone in ("start_date", "auto_renewal", "email_notifications"):
            self.assertFalse(meta.has_field(gone), f"{gone} exists now: the removed UI may be restorable")
        html = self._render_label_page_2688("my_dues_schedule", self._member_with_frequency("Annual"))
        # control: the page really rendered the schedule card
        self.assertIn("Billing Frequency", html)
        # control: a row that is still there renders in exactly this span shape
        self.assertIn(self._label_span("Payment Method"), html)
        for dead_label in ("Start Date", "End Date", "Auto-Renewal", "Notification"):
            self.assertNotIn(self._label_span(dead_label), html)
            self.assertNotIn(dead_label, html)
