import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    LIVE_CAPABLE_CATEGORIES,
    DataCategory,
    DataRetentionPolicy,
)

MIN_RETENTION_DAYS = 30


class DataRetentionSettings(Document):
    @staticmethod
    def default_category_rows():
        """Nine rows seeded from the engine's code-level defaults."""
        rows = []
        for category in DataCategory:
            rows.append(
                {
                    "category": category.value,
                    "retention_days": DataRetentionPolicy.DEFAULT_RETENTION_PERIODS[category],
                    "action": DataRetentionPolicy.DEFAULT_RETENTION_ACTIONS[category].value,
                    "live_enabled": 0,
                }
            )
        return rows

    @frappe.whitelist()
    def reset_category_policies(self):
        """Replace the table with the code defaults (button + patch use this)."""
        self.set("category_policies", [])
        for row in self.default_category_rows():
            self.append("category_policies", row)
        self.save()

    def validate(self):
        self._validate_no_duplicate_categories()
        self._validate_retention_minimums()
        self._validate_live_capability()

    def _validate_no_duplicate_categories(self):
        seen = set()
        for row in self.category_policies:
            if row.category in seen:
                frappe.throw(_("Duplicate retention category: {0}").format(row.category))
            seen.add(row.category)

    def _validate_retention_minimums(self):
        for row in self.category_policies:
            if not row.retention_days or int(row.retention_days) < MIN_RETENTION_DAYS:
                frappe.throw(
                    _("Retention Days for {0} must be at least {1}.").format(row.category, MIN_RETENTION_DAYS)
                )

    def _validate_live_capability(self):
        capable = {c.value for c in LIVE_CAPABLE_CATEGORIES}
        for row in self.category_policies:
            if row.live_enabled and row.category not in capable:
                frappe.throw(
                    _(
                        "Live purging is not yet available for category '{0}'. "
                        "Only {1} is live-capable; leave Live Enabled off."
                    ).format(row.category, ", ".join(sorted(capable)))
                )
