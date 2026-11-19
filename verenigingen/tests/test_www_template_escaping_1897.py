"""www/ pages and verenigingen_payments templates escape typed values (#1897, sibling of #1890).

Frappe renders these with Jinja autoescape OFF (measured in #1890), so a bare ``{{ x }}`` prints
``<i>x</i>`` as a live tag. Each test renders the REAL template file through ``frappe.get_template``
(the same jenv the page renderer and ``SEPAMandateNotifications`` use) with a markup-bearing value and
asserts the value comes out escaped and the raw tag is gone.

Declared shortcuts: the context is built by hand instead of by each page's ``get_context``
(``mollie_checkout.get_context`` needs a Mollie Settings row; the SEPA contexts are built by
``SEPAMandateNotifications._prepare_*_context``, which does not escape), so these prove the TEMPLATE
escapes, not that a given caller passes a hostile value.

Run:
    bench --site test_site_8 run-tests --app verenigingen --module verenigingen.tests.test_www_template_escaping_1897
"""

import json
import re

import frappe
from frappe.tests import IntegrationTestCase

RAW = '<i>x</i> & "y"'
ESCAPED = "&lt;i&gt;x&lt;/i&gt; &amp; &#34;y&#34;"
# A plain dict: outside a request frappe.form_dict is not JSON-serialisable, and the page prints it
# through |tojson.
FRAPPE_STUB = {"form_dict": {}, "utils": frappe.utils, "format": frappe.format}
PAYMENTS = "verenigingen/verenigingen_payments/templates"


def render_www_template(path, context, block="page_content"):
    """Render a template; for a page that extends web.html, only the named content block.

    Shortcut, declared: the base layout needs a full website context (``base_template_path`` ...),
    and none of the values under test is printed outside ``page_content``.
    """
    template = frappe.get_template(path)
    if block in template.blocks:
        return "".join(template.blocks[block](template.new_context(context)))
    return template.render(context)


class TestWwwTemplateEscaping1897(IntegrationTestCase):
    def assert_escaped_once(self, html, field):
        self.assertNotIn("<i>x</i>", html, f"{field}: raw markup reached the page")
        self.assertIn(ESCAPED, html, f"{field}: value is not HTML-escaped (or is escaped twice)")

    def test_mollie_checkout_escapes_reflected_form_values(self):
        """description, payer_email, order_id, title and amount come straight from frappe.form_dict."""
        for field in ("description", "payer_email", "order_id", "title"):
            context = {
                "title": "T",
                "description": "D",
                "payer_email": "a@example.org",
                "order_id": "O1",
                "amount_formatted": "1.00",
                "reference_doctype": "Sales Invoice",
                "reference_docname": "SINV-1",
                "gateway_name": "Default",
                "test_mode": 0,
                "frappe": FRAPPE_STUB,
                field: RAW,
            }
            with self.subTest(field=field):
                html = render_www_template(f"{PAYMENTS}/pages/mollie_checkout.html", context)
                self.assert_escaped_once(html, field)

    def test_mollie_checkout_page_config_is_json_not_string_interpolation(self):
        """reference_docname sits in a JSON <script>: a quote or </script> must not break out of it."""
        hostile = 'x"</script><i>y</i>'
        html = render_www_template(
            f"{PAYMENTS}/pages/mollie_checkout.html",
            {
                "reference_doctype": "Sales Invoice",
                "reference_docname": hostile,
                "gateway_name": "Default",
                "test_mode": 1,
                "amount_formatted": "1.00",
                "frappe": FRAPPE_STUB,
            },
        )
        config = re.search(r'<script type="application/json" id="page-config">(.*?)</script>', html, re.S)
        self.assertIsNotNone(config, "page-config script block was cut short by the value")
        parsed = json.loads(config.group(1))
        self.assertEqual(parsed["reference_docname"], hostile)
        self.assertIs(parsed["test_mode"], True)
        self.assertNotIn("<i>y</i>", html)

    def test_sepa_mandate_emails_escape_member_supplied_values(self):
        base = {
            "company_name": "Co",
            "member_name": "M",
            "mandate_id": "SEPA-1",
            "iban": "NL**",
            "bank_name": "B",
            "sign_date": "d",
            "cancellation_date": "d",
            "cancellation_reason": "r",
            "expiry_date": "d",
            "days_until_expiry": 5,
            "current_year": 2026,
            "website_url": "https://example.org",
            "renewal_link": "https://example.org/r",
        }
        cases = {
            "sepa_mandate_created": ("member_name", "bank_name", "company_name"),
            "sepa_mandate_cancelled": ("member_name", "cancellation_reason", "company_name"),
            "sepa_mandate_expiring": ("member_name", "company_name"),
        }
        for template, fields in cases.items():
            for field in fields:
                with self.subTest(template=template, field=field):
                    html = render_www_template(f"{PAYMENTS}/emails/{template}.html", {**base, field: RAW})
                    self.assert_escaped_once(html, f"{template}.{field}")

    def test_word_lid_form_escapes_door_name_and_default_plan(self):
        for field, context in (
            ("door.name", {"door": {"name": RAW, "title": "T", "form_shape": "Short"}}),
            ("door.form_shape", {"door": {"name": "n", "title": "T", "form_shape": RAW}}),
            ("default_plan_id", {"door": {"name": "n", "title": "T", "form_shape": "Short"}, "default_plan_id": RAW}),
        ):
            with self.subTest(field=field):
                html = render_www_template(
                    "verenigingen/www/word-lid.html",
                    {"title": "T", "primary_color": "#cf3131", "plans": [], "frappe": FRAPPE_STUB, **context},
                )
                self.assert_escaped_once(html, field)

    def test_monitoring_dashboard_alert_name_is_not_in_a_js_string(self):
        """alert.name was spliced into onclick="...('{{ name }}')": a quote broke out of the JS string."""
        hostile = "x');alert(1);('"
        html = render_www_template(
            "verenigingen/www/monitoring_dashboard.html",
            {
                "title": "T",
                "frappe": FRAPPE_STUB,
                "system_metrics": {
                    "members": {"active": 1, "total": 2},
                    "volunteers": {"active": 1, "total": 2},
                    "sepa": {"active_mandates": 1, "recent_batches": 1, "pending_payments": 1},
                    "errors": {"last_24h": 0, "last_hour": 0},
                    "invoices": {"paid": 1, "draft": 1, "submitted": 1},
                },
                "performance_metrics": {
                    "database": {"total_tables": 1, "error_logs_size": 1, "recent_queries": 1},
                    "system": {"active_users": 1, "background_jobs": 1, "cache_status": "ok"},
                    "business": {
                        "daily_transactions": 1,
                        "payment_success_rate": 1,
                        "member_growth": {"error": False, "today": 1},
                    },
                },
                "recent_errors": [],
                "audit_summary": [],
                "alerts": [frappe._dict(alert_type="a", severity="low", message="m", status="Active", name=hostile)],
            },
            block="content",
        )
        self.assertNotIn(f"acknowledgeAlert('{hostile}')", html)
        self.assertNotIn(f"resolveAlert('{hostile}')", html)
        self.assertIn('data-alert="x&#39;);alert(1);(&#39;"', html)
