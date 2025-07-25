"""
Correct E-Boekhouden to ERPNext Implementation Example
Shows how to properly fetch full mutation details and map all fields
"""

from typing import Dict, List, Optional

import frappe
from frappe.utils import add_days, flt, now


class EBoekhoudenCorrectImporter:
    """Demonstrates correct way to import e-boekhouden data"""

    def __init__(self, company: str):
        self.company = company
        self.btw_code_map = self._init_btw_mapping()
        self.default_cost_center = self._get_default_cost_center()

    def import_mutation(self, mutation_id: int) -> Dict:
        """Import a single mutation with all details"""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # CRITICAL: Fetch FULL mutation details, not just summary!
        mutation_detail = iterator.fetch_mutation_detail(mutation_id)

        if not mutation_detail:
            return {"success": False, "error": f"Mutation {mutation_id} not found"}

        # Route to appropriate handler based on type
        mutation_type = mutation_detail.get("type", 0)

        if mutation_type == 1:  # Purchase Invoice
            return self._create_purchase_invoice(mutation_detail)
        elif mutation_type == 2:  # Sales Invoice
            return self._create_sales_invoice(mutation_detail)
        elif mutation_type in [3, 4]:  # Payment Entry
            return self._create_payment_entry(mutation_detail)
        else:  # Journal Entry
            return self._create_journal_entry(mutation_detail)

    def _create_sales_invoice(self, mutation: Dict) -> Dict:
        """Create Sales Invoice with proper field mapping"""
        try:
            si = frappe.new_doc("Sales Invoice")

            # Basic fields
            si.company = self.company
            si.posting_date = mutation.get("date")
            si.set_posting_time = 1

            # Customer - Create or get by name, not ID!
            customer = self._get_or_create_customer(mutation.get("relationId"))
            si.customer = customer

            # Currency
            si.currency = "EUR"
            si.conversion_rate = 1.0

            # Payment terms and due date
            payment_days = mutation.get("Betalingstermijn", 30)
            if payment_days:
                si.payment_terms_template = self._get_payment_terms_template(payment_days)
                si.due_date = add_days(si.posting_date, payment_days)

            # References
            if mutation.get("Referentie"):
                si.po_no = mutation.get("Referentie")

            # Description
            si.remarks = mutation.get("description", "")

            # Check if credit note
            total_amount = flt(mutation.get("amount", 0))
            si.is_return = total_amount < 0

            # Custom fields for tracking
            si.custom_eboekhouden_mutation_nr = str(mutation.get("id"))
            si.custom_eboekhouden_invoice_number = mutation.get("invoiceNumber")
            si.custom_eboekhouden_import_date = now()

            # CRITICAL: Process line items from Regels
            if "Regels" in mutation and mutation["Regels"]:
                # Process each line item
                for regel in mutation["Regels"]:
                    si.append("items", self._map_line_item(regel, "sales"))

                # Add VAT/BTW lines based on line items
                self._add_tax_lines(si, mutation["Regels"], "sales")
            else:
                # Fallback for mutations without line details
                si.append("items", self._create_fallback_line_item(mutation, "sales"))

            # Set taxes template if we have taxes
            if si.taxes and len(si.taxes) > 0:
                si.taxes_and_charges = self._get_or_create_tax_template("Sales Taxes EUR", si.taxes, "sales")

            si.save()
            si.submit()

            return {
                "success": True,
                "doctype": "Sales Invoice",
                "name": si.name,
                "customer": si.customer,
                "total": si.grand_total,
            }

        except Exception as e:
            frappe.log_error(f"Error creating sales invoice: {str(e)}", "E-Boekhouden Import")
            return {"success": False, "error": str(e)}

    def _create_purchase_invoice(self, mutation: Dict) -> Dict:
        """Create Purchase Invoice with proper field mapping"""
        try:
            pi = frappe.new_doc("Purchase Invoice")

            # Basic fields
            pi.company = self.company
            pi.posting_date = mutation.get("date")
            pi.bill_date = mutation.get("date")
            pi.set_posting_time = 1

            # Supplier - Create or get by name, not ID!
            supplier = self._get_or_create_supplier(mutation.get("relationId"))
            pi.supplier = supplier

            # Currency
            pi.currency = "EUR"
            pi.conversion_rate = 1.0

            # Invoice number from supplier
            if mutation.get("invoiceNumber"):
                pi.bill_no = mutation.get("invoiceNumber")
                pi.supplier_invoice_no = mutation.get("invoiceNumber")

            # Payment terms and due date
            payment_days = mutation.get("Betalingstermijn", 30)
            if payment_days:
                pi.payment_terms_template = self._get_payment_terms_template(payment_days)
                pi.due_date = add_days(pi.bill_date, payment_days)

            # Description
            pi.remarks = mutation.get("description", "")

            # Check if debit note
            total_amount = flt(mutation.get("amount", 0))
            pi.is_return = total_amount < 0

            # Custom fields
            pi.custom_eboekhouden_mutation_nr = str(mutation.get("id"))
            pi.custom_eboekhouden_import_date = now()

            # Process line items
            if "Regels" in mutation and mutation["Regels"]:
                for regel in mutation["Regels"]:
                    pi.append("items", self._map_line_item(regel, "purchase"))

                # Add VAT/BTW lines
                self._add_tax_lines(pi, mutation["Regels"], "purchase")
            else:
                pi.append("items", self._create_fallback_line_item(mutation, "purchase"))

            # Set taxes template
            if pi.taxes and len(pi.taxes) > 0:
                pi.taxes_and_charges = self._get_or_create_tax_template(
                    "Purchase Taxes EUR", pi.taxes, "purchase"
                )

            pi.save()
            pi.submit()

            return {
                "success": True,
                "doctype": "Purchase Invoice",
                "name": pi.name,
                "supplier": pi.supplier,
                "total": pi.grand_total,
            }

        except Exception as e:
            frappe.log_error(f"Error creating purchase invoice: {str(e)}", "E-Boekhouden Import")
            return {"success": False, "error": str(e)}

    def _map_line_item(self, regel: Dict, transaction_type: str) -> Dict:
        """Map e-boekhouden line item (Regel) to ERPNext item"""

        # Get or create item based on description
        item_code = self._get_or_create_item(
            description=regel.get("Omschrijving", "Service"), unit=regel.get("Eenheid", "Nos")
        )

        # Calculate amounts
        qty = flt(regel.get("Aantal", 1))
        rate = flt(regel.get("Prijs", 0))
        amount = qty * rate

        # Get account from Grootboek number
        account = self._get_account_from_grootboek(regel.get("GrootboekNummer"))

        line_item = {
            "item_code": item_code,
            "item_name": regel.get("Omschrijving", "Service"),
            "description": regel.get("Omschrijving", ""),
            "qty": qty,
            "uom": self._map_unit_of_measure(regel.get("Eenheid", "Nos")),
            "rate": rate,
            "amount": amount,
        }

        # Set appropriate account
        if transaction_type == "sales":
            line_item["income_account"] = account or self._get_default_income_account()
        else:
            line_item["expense_account"] = account or self._get_default_expense_account()

        # Cost center if specified
        if regel.get("KostenplaatsId"):
            cost_center = self._get_cost_center(regel.get("KostenplaatsId"))
            if cost_center:
                line_item["cost_center"] = cost_center

        return line_item

    def _add_tax_lines(self, invoice: frappe._dict, regels: List[Dict], invoice_type: str):
        """Add tax lines based on BTW codes in line items"""

        # Group amounts by BTW code
        btw_summary = {}

        for regel in regels:
            btw_code = regel.get("BTWCode", "").upper()

            if btw_code and btw_code != "GEEN":
                if btw_code not in btw_summary:
                    btw_summary[btw_code] = {
                        "taxable_amount": 0,
                        "tax_amount": 0,
                        "rate": self._get_btw_rate(btw_code),
                    }

                # Calculate line total
                line_total = flt(regel.get("Aantal", 1)) * flt(regel.get("Prijs", 0))
                tax_rate = btw_summary[btw_code]["rate"]

                # Add to summary
                btw_summary[btw_code]["taxable_amount"] += line_total
                btw_summary[btw_code]["tax_amount"] += line_total * tax_rate / 100

        # Create tax lines
        for btw_code, tax_data in btw_summary.items():
            if tax_data["tax_amount"] > 0:
                tax_account = self._get_tax_account(btw_code, invoice_type)

                invoice.append(
                    "taxes",
                    {
                        "charge_type": "Actual",
                        "account_head": tax_account,
                        "tax_amount": tax_data["tax_amount"],
                        "description": self._get_btw_description(btw_code),
                        "rate": 0,  # Using actual amount
                        "base_tax_amount": tax_data["tax_amount"],
                        "base_total": tax_data["taxable_amount"],
                    },
                )

    def _get_or_create_customer(self, relation_id: str) -> str:
        """Get or create customer by relation ID"""
        if not relation_id:
            return "Guest Customer"

        # First check if we have a mapping
        existing = frappe.db.get_value("Customer", {"custom_eboekhouden_relation_id": relation_id}, "name")

        if existing:
            return existing

        # Try to fetch relation details from API if possible
        # For now, create with relation ID as name
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"E-Boekhouden {relation_id}"
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"
        customer.custom_eboekhouden_relation_id = relation_id
        customer.insert(ignore_permissions=True)

        return customer.name

    def _get_or_create_supplier(self, relation_id: str) -> str:
        """Get or create supplier by relation ID"""
        if not relation_id:
            return (
                frappe.db.get_value("Supplier", {"supplier_name": "Default Supplier"}, "name")
                or self._create_default_supplier()
            )

        # Check for existing mapping
        existing = frappe.db.get_value("Supplier", {"custom_eboekhouden_relation_id": relation_id}, "name")

        if existing:
            return existing

        # Create new supplier
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = f"E-Boekhouden {relation_id}"
        supplier.supplier_group = "All Supplier Groups"
        supplier.custom_eboekhouden_relation_id = relation_id
        supplier.insert(ignore_permissions=True)

        return supplier.name

    def _get_payment_terms_template(self, days: int) -> Optional[str]:
        """Get or create payment terms template"""
        template_name = f"Net {days}"

        if not frappe.db.exists("Payment Terms Template", template_name):
            template = frappe.new_doc("Payment Terms Template")
            template.template_name = template_name
            template.append(
                "terms",
                {
                    "due_date_based_on": "Day(s) after invoice date",
                    "credit_days": days,
                    "invoice_portion": 100,
                },
            )
            template.insert(ignore_permissions=True)

        return template_name

    def _get_btw_rate(self, btw_code: str) -> float:
        """Get BTW rate from code"""
        if btw_code in self.btw_code_map:
            return self.btw_code_map[btw_code]["rate"]

        # Try to parse rate from code
        if "21" in btw_code:
            return 21.0
        elif "9" in btw_code:
            return 9.0
        elif "6" in btw_code:
            return 6.0
        else:
            return 0.0

    def _get_btw_description(self, btw_code: str) -> str:
        """Get BTW description from code"""
        if btw_code in self.btw_code_map:
            return self.btw_code_map[btw_code]["description"]
        return f"BTW {btw_code}"

    def _init_btw_mapping(self) -> Dict:
        """Initialize BTW code mapping"""
        return {
            # Sales VAT
            "HOOG_VERK_21": {"rate": 21, "description": "BTW verkoop hoog 21%"},
            "LAAG_VERK_9": {"rate": 9, "description": "BTW verkoop laag 9%"},
            "LAAG_VERK_6": {"rate": 6, "description": "BTW verkoop laag 6%"},
            # Purchase VAT
            "HOOG_INK_21": {"rate": 21, "description": "BTW inkoop hoog 21%"},
            "LAAG_INK_9": {"rate": 9, "description": "BTW inkoop laag 9%"},
            "LAAG_INK_6": {"rate": 6, "description": "BTW inkoop laag 6%"},
            # Special
            "GEEN": {"rate": 0, "description": "Geen BTW"},
            "BU_EU_VERK": {"rate": 0, "description": "Buiten EU verkoop"},
            "VERL_VERK": {"rate": 0, "description": "BTW verlegd"},
        }

    def _get_tax_account(self, btw_code: str, invoice_type: str) -> str:
        """Get tax account for BTW code"""
        # This should be configurable, but for now use defaults
        if invoice_type == "sales":
            if "21" in btw_code:
                return self._ensure_account_exists("BTW te betalen hoog 21%", "Tax", "Liability")
            elif "9" in btw_code:
                return self._ensure_account_exists("BTW te betalen laag 9%", "Tax", "Liability")
            elif "6" in btw_code:
                return self._ensure_account_exists("BTW te betalen laag 6%", "Tax", "Liability")
        else:  # purchase
            if "21" in btw_code:
                return self._ensure_account_exists("Voorbelasting hoog 21%", "Tax", "Asset")
            elif "9" in btw_code:
                return self._ensure_account_exists("Voorbelasting laag 9%", "Tax", "Asset")
            elif "6" in btw_code:
                return self._ensure_account_exists("Voorbelasting laag 6%", "Tax", "Asset")

        return self._ensure_account_exists("BTW algemeen", "Tax", "Liability")

    def _ensure_account_exists(self, account_name: str, account_type: str, root_type: str) -> str:
        """Ensure account exists, create if not"""
        existing = frappe.db.get_value(
            "Account", {"account_name": account_name, "company": self.company}, "name"
        )

        if existing:
            return existing

        # Get parent account
        parent = frappe.db.get_value(
            "Account",
            {"account_type": account_type, "is_group": 1, "company": self.company, "root_type": root_type},
            "name",
        )

        if not parent:
            parent = frappe.db.get_value(
                "Account", {"is_group": 1, "company": self.company, "root_type": root_type}, "name"
            )

        # Create account
        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.account_type = account_type
        account.root_type = root_type
        account.parent_account = parent
        account.company = self.company
        account.insert(ignore_permissions=True)

        return account.name

    def _get_or_create_item(self, description: str, unit: str = "Nos") -> str:
        """Get or create item based on description"""
        # For now, create generic items. In production, you'd want smarter matching
        if not description:
            return "Service"

        # Check if item exists
        item_name = description[:140]  # Limit length
        existing = frappe.db.get_value("Item", {"item_name": item_name}, "name")

        if existing:
            return existing

        # Create new item
        item = frappe.new_doc("Item")
        item.item_code = item_name[:20]  # Short code
        item.item_name = item_name
        item.item_group = "Services"
        item.stock_uom = self._map_unit_of_measure(unit)
        item.is_stock_item = 0
        item.is_sales_item = 1
        item.is_purchase_item = 1

        try:
            item.insert(ignore_permissions=True)
            return item.name
        except frappe.DuplicateEntryError:
            # Try with timestamp
            item.item_code = f"{item_name[:15]}_{now()[-5:]}"
            item.insert(ignore_permissions=True)
            return item.name

    def _map_unit_of_measure(self, unit: str) -> str:
        """Map Dutch units to ERPNext UOM"""
        uom_map = {
            "stuk": "Nos",
            "stuks": "Nos",
            "uur": "Hour",
            "uren": "Hour",
            "dag": "Day",
            "dagen": "Day",
            "maand": "Month",
            "kg": "Kg",
            "liter": "Litre",
            "m2": "Square Meter",
            "m3": "Cubic Meter",
        }

        return uom_map.get(unit.lower(), "Nos") if unit else "Nos"

    def _get_default_cost_center(self) -> str:
        """Get default cost center for company"""
        return frappe.db.get_value("Company", self.company, "cost_center")

    def _get_or_create_tax_template(self, template_name: str, taxes: List, tax_type: str) -> str:
        """Get or create tax template based on actual taxes"""
        # For now, return None to let ERPNext calculate
        # In production, you'd create proper tax templates
        return None


# Whitelisted function to test
@frappe.whitelist()
def test_correct_import(mutation_id: int):
    """Test the correct import implementation"""
    company = frappe.get_single("E-Boekhouden Settings").default_company

    if not company:
        return {"success": False, "error": "No default company configured"}

    importer = EBoekhoudenCorrectImporter(company)
    result = importer.import_mutation(int(mutation_id))

    return result
