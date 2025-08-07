import frappe
from frappe.model.document import Document


class EBoekhoudenCostCenterMapping(Document):
    def validate(self):
        """Validate cost center mapping settings"""
        if self.create_cost_center and not self.cost_center_name:
            # Auto-generate cost center name from group name
            self.cost_center_name = self.group_name

        # Clean up cost center name
        if self.cost_center_name:
            self.cost_center_name = self.cost_center_name.strip()

    def before_insert(self):
        """Set default values before insert"""
        if not self.cost_center_name and self.group_name:
            self.cost_center_name = self.group_name
