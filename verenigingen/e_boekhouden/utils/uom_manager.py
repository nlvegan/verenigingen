"""
Enhanced Unit of Measure Management for E-Boekhouden Integration
Handles Dutch UOM conversions and creates missing UOMs automatically
"""

import frappe
from frappe.utils import cstr


class UOMManager:
    """Manages Unit of Measure conversions and creation"""

    # Extended Dutch to ERPNext UOM mappings
    DUTCH_UOM_MAP = {
        # Quantity units
        "stuk": "Nos",
        "stuks": "Nos",
        "st": "Nos",
        "st.": "Nos",
        "stk": "Nos",
        "aantal": "Nos",
        "nos": "Nos",
        "unit": "Unit",
        "eenheid": "Unit",
        # Time units
        "uur": "Hour",
        "uren": "Hour",
        "u": "Hour",
        "dag": "Day",
        "dagen": "Day",
        "week": "Week",
        "weken": "Week",
        "maand": "Month",
        "maanden": "Month",
        "mnd": "Month",
        "jaar": "Year",
        "jaren": "Year",
        "jr": "Year",
        "kwartaal": "Quarter",
        "kwartalen": "Quarter",
        # Weight units
        "kg": "Kg",
        "kilogram": "Kg",
        "gram": "Gram",
        "g": "Gram",
        "ton": "Tonne",
        "pond": "Lbs",
        "lbs": "Lbs",
        # Volume units
        "liter": "Litre",
        "l": "Litre",
        "ml": "Ml",
        "milliliter": "Ml",
        "m3": "Cubic Meter",
        "kubieke meter": "Cubic Meter",
        # Length units
        "m": "Meter",
        "meter": "Meter",
        "cm": "Cm",
        "centimeter": "Cm",
        "mm": "Mm",
        "millimeter": "Mm",
        "km": "Km",
        "kilometer": "Km",
        # Area units
        "m2": "Sq Meter",
        "vierkante meter": "Sq Meter",
        "hectare": "Hectare",
        "ha": "Hectare",
        # Service/subscription units
        "abonnement": "Subscription",
        "licentie": "License",
        "gebruiker": "User",
        "seat": "Seat",
        "account": "Account",
        # Percentage/rate units
        "%": "Percent",
        "procent": "Percent",
        "percentage": "Percent",
        "promille": "Per Mille",
        "‰": "Per Mille",
        # Package units
        "doos": "Box",
        "dozen": "Box",
        "pak": "Pack",
        "pakken": "Pack",
        "pallet": "Pallet",
        "set": "Set",
        "bundel": "Bundle",
        "krat": "Crate",
        "kratten": "Crate",
        # Custom business units
        "project": "Project",
        "dienst": "Service",
        "sessie": "Session",
        "beurt": "Turn",
        "keer": "Time",
        "maal": "Time",
        "reis": "Trip",
        "rit": "Trip",
        # Financial units
        "factuur": "Invoice",
        "post": "Entry",
        "transactie": "Transaction",
    }

    # UOM categories for automatic conversion setup
    UOM_CATEGORIES = {
        "time": ["Hour", "Day", "Week", "Month", "Quarter", "Year"],
        "weight": ["Gram", "Kg", "Tonne", "Lbs"],
        "volume": ["Ml", "Litre", "Cubic Meter"],
        "length": ["Mm", "Cm", "Meter", "Km"],
        "area": ["Sq Meter", "Hectare"],
        "quantity": ["Nos", "Unit", "Box", "Pack", "Pallet", "Set", "Bundle", "Crate"],
        "service": ["Service", "Session", "Project", "Subscription", "License"],
        "financial": ["Invoice", "Entry", "Transaction"],
    }

    def __init__(self):
        self.ensure_base_uoms_exist()

    def ensure_base_uoms_exist(self):
        """Ensure all base UOMs exist in the system"""
        # Get unique ERPNext UOMs from mapping
        required_uoms = set(self.DUTCH_UOM_MAP.values())

        # Add custom UOMs that might be needed
        custom_uoms = [
            "Subscription",
            "License",
            "User",
            "Seat",
            "Account",
            "Project",
            "Service",
            "Session",
            "Turn",
            "Time",
            "Trip",
            "Invoice",
            "Entry",
            "Transaction",
            "Quarter",
            "Per Mille",
            "Bundle",
            "Crate",
        ]
        required_uoms.update(custom_uoms)

        for uom_name in required_uoms:
            self._ensure_uom_exists(uom_name)

    def _ensure_uom_exists(self, uom_name):
        """Create UOM if it doesn't exist"""
        if not frappe.db.exists("UOM", uom_name):
            try:
                uom = frappe.new_doc("UOM")
                uom.uom_name = uom_name
                uom.enabled = 1

                # Set appropriate symbol
                symbols = {
                    "Percent": "%",
                    "Per Mille": "‰",
                    "Hour": "hr",
                    "Day": "d",
                    "Week": "wk",
                    "Month": "mo",
                    "Year": "yr",
                    "Quarter": "qtr",
                }

                if uom_name in symbols:
                    uom.symbol = symbols[uom_name]

                # Security: UOM setup during eBoekhouden import - system configuration
                # No commit here: the insert participates in the caller's
                # transaction (request-level, or a per-mutation savepoint during
                # batch import). An inserted UOM is already visible to later
                # reads in the same transaction.
                uom.insert(ignore_permissions=True)

            except Exception as e:
                # UOM might already exist or other error
                frappe.log_error(f"Could not create UOM {uom_name}: {str(e)}")

    def map_uom(self, dutch_uom):
        """Map Dutch UOM to ERPNext UOM"""
        if not dutch_uom:
            return "Nos"

        # Clean and normalize the input
        dutch_uom_clean = cstr(dutch_uom).lower().strip()

        # Direct mapping
        if dutch_uom_clean in self.DUTCH_UOM_MAP:
            erpnext_uom = self.DUTCH_UOM_MAP[dutch_uom_clean]
            self._ensure_uom_exists(erpnext_uom)
            return erpnext_uom

        # Check if it's already a valid ERPNext UOM
        if frappe.db.exists("UOM", dutch_uom):
            return dutch_uom

        # Try to create custom UOM if it doesn't exist
        custom_uom = self._create_custom_uom(dutch_uom)
        if custom_uom:
            return custom_uom

        # Default fallback
        return "Nos"

    def _create_custom_uom(self, uom_name):
        """Create a custom UOM for unmapped units"""
        try:
            # Clean the name
            clean_name = cstr(uom_name).strip()
            if not clean_name:
                return None

            # Check if it already exists
            if frappe.db.exists("UOM", clean_name):
                return clean_name

            # Create new UOM
            uom = frappe.new_doc("UOM")
            uom.uom_name = clean_name
            uom.enabled = 1
            uom.custom_eboekhouden_uom = 1  # Mark as E-Boekhouden import
            # Security: UOM creation during E-Boekhouden data migration.
            # Creates master data (Units of Measure) from external accounting system.
            # No commit: participates in the caller's transaction (see
            # _ensure_uom_exists) so batch-import savepoints stay intact.
            uom.insert(ignore_permissions=True)
            return clean_name

        except Exception as e:
            frappe.log_error(f"Could not create custom UOM {uom_name}: {str(e)}")
            return None

    def setup_conversions(self):
        """UOM conversions are intentionally not seeded here.

        The previous implementation defined a hard-coded conversion table whose
        every entry was inverted relative to ERPNext's ``1 from_uom = value * to_uom``
        convention -- e.g. it declared ``("Gram", "Kg", 1000)`` ("1 Gram = 1000 Kg")
        when the correct relation is ``1 Kg = 1000 Gram``. Those inserts also never
        succeeded: they omitted the mandatory ``category`` field, so every row raised
        MandatoryError which a bare ``except`` swallowed. The table was therefore both
        wrong and a no-op for the entire life of the code.

        ERPNext already ships the correct Mass conversions, and eBoekhouden's
        currency-based import does not rely on physical-UOM conversion factors, so the
        conversions are deliberately left unseeded rather than re-introduced in the
        correct direction. This method is kept as an explicit, documented no-op so that
        ``setup_dutch_uoms`` keeps a stable surface and no inverted data is ever created.
        """
        return

    def get_item_uom_conversions(self, item_code, base_uom):
        """Get or create item-specific UOM conversions"""
        # This would be used for items that have specific conversion rates
        # For example, a box of specific product might contain 24 units
        pass

    @staticmethod
    def get_uom_for_category(item_group):
        """Suggest appropriate UOM based on item group"""
        uom_suggestions = {
            # Updated to use existing item groups only
            "Services": "Hour",
            "Products": "Unit",
            "Expense Items": "Unit",
            "Consumable": "Unit",
            "Other": "Unit",
            "Revenue Items": "Unit",
            "Cost of Goods Sold Items": "Unit",
        }

        return uom_suggestions.get(item_group, "Unit")


# Convenience function for use in other modules
def map_unit_of_measure(dutch_uom):
    """Map Dutch UOM to ERPNext UOM"""
    manager = UOMManager()
    return manager.map_uom(dutch_uom)


def setup_dutch_uoms():
    """Setup all Dutch UOMs and conversions"""
    manager = UOMManager()
    manager.ensure_base_uoms_exist()
    manager.setup_conversions()
    return {"status": "success", "message": "Dutch UOMs setup completed"}
