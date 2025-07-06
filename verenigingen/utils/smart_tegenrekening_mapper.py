import frappe


class SmartTegenrekeningMapper:
    """Smart mapping system for E-Boekhouden tegenrekening codes to ERPNext items"""

    def __init__(self, company="Ned Ver Vegan"):
        self.company = company
        self._ledger_mapping_cache = None
        self._account_cache = {}
        self._logged_missing_ledgers = set()  # Track logged missing ledgers to avoid spam

    def get_item_for_tegenrekening(self, account_code, description="", transaction_type="purchase", amount=0):
        """
        Get appropriate ERPNext item for an E-Boekhouden tegenrekening code

        Args:
            account_code: E-Boekhouden account code (e.g., "80001", "42200")
            description: Transaction description (for fallback mapping)
            transaction_type: "purchase" or "sales"
            amount: Transaction amount (for validation)

        Returns:
            dict: {
                'item_code': ERPNext item code,
                'item_name': Item name,
                'account': ERPNext account for this transaction,
                'item_group': Item group
            }
        """

        if not account_code:
            return self._get_fallback_item(transaction_type, description)

        # Strategy 1: Use pre-created smart items
        smart_item = self._get_smart_item(account_code)
        if smart_item:
            return smart_item

        # Strategy 2: Dynamic item creation based on account
        dynamic_item = self._create_dynamic_item(account_code, description, transaction_type)
        if dynamic_item:
            return dynamic_item

        # Strategy 3: Fallback to generic item
        return self._get_fallback_item(transaction_type, description)

    def _get_smart_item(self, account_code):
        """Get pre-created smart item for account code"""
        item_code = f"EB-{account_code}"

        item_data = frappe.db.get_value("Item", item_code, ["name", "item_name", "item_group"], as_dict=True)

        if item_data:
            # Get account from E-Boekhouden mapping
            account = self._get_account_by_code(account_code)

            return {
                "item_code": item_data.name,
                "item_name": item_data.item_name,
                "account": account,
                "item_group": item_data.item_group,
                "source": "smart_mapping",
            }

        return None

    def _create_dynamic_item(self, account_code, description, transaction_type):
        """Create item dynamically if account exists but item doesn't"""

        # Check if we have an ERPNext account for this code
        erpnext_account = self._get_account_by_code(account_code)
        if not erpnext_account:
            return None

        # Get account details
        account_details = frappe.db.get_value(
            "Account", erpnext_account, ["account_name", "account_type", "root_type"], as_dict=True
        )

        if not account_details:
            return None

        # Generate item name and properties
        item_code = f"EB-{account_code}"
        item_name = self._generate_item_name(account_details.account_name, account_code)

        # Determine item properties
        # Always enable both sales and purchase for flexibility
        is_sales_item = 1
        is_purchase_item = 1
        item_group = "E-Boekhouden Import"

        # Check account name for specific patterns to determine proper categorization
        account_name_lower = account_details.account_name.lower()

        if account_details.account_type == "Income Account":
            item_group = "Revenue Items"
        elif account_details.account_type == "Cost of Goods Sold":
            item_group = "Cost of Goods Sold Items"
        elif account_details.account_type == "Expense Account":
            item_group = "Expense Items"
        # Special handling for material/inkoop accounts that should be COGS
        elif any(
            keyword in account_name_lower for keyword in ["inkoop", "materiaal", "grondstoffen", "kostprijs"]
        ):
            item_group = "Cost of Goods Sold Items"
        elif transaction_type == "sales":
            item_group = "Revenue Items"
        else:
            item_group = "Expense Items"

        try:
            # Create the item
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = item_name
            item.item_group = item_group
            item.stock_uom = "Nos"
            item.is_stock_item = 0
            item.is_sales_item = is_sales_item
            item.is_purchase_item = is_purchase_item

            # Add Item Default to link to the expense/income account
            item.append(
                "item_defaults",
                {
                    "company": self.company,
                    "expense_account": erpnext_account if is_purchase_item else None,
                    "income_account": erpnext_account if is_sales_item else None,
                },
            )

            item.insert(ignore_permissions=True)

            return {
                "item_code": item_code,
                "item_name": item_name,
                "account": erpnext_account,
                "item_group": item_group,
                "source": "dynamic_creation",
            }

        except Exception as e:
            frappe.log_error(f"Failed to create dynamic item for account {account_code}: {str(e)}")
            return None

    def _get_account_by_code(self, account_code):
        """Get ERPNext account by E-Boekhouden code"""
        if account_code in self._account_cache:
            return self._account_cache[account_code]

        # First check if this is a ledger ID (all digits) vs account code
        if str(account_code).isdigit() and len(str(account_code)) > 5:
            # This looks like a ledger ID, not an account code
            # Try to get the actual account code from ledger mapping
            from .eboekhouden_ledger_mapping import get_account_code_from_ledger_id

            mapped_code = get_account_code_from_ledger_id(account_code)
            if mapped_code:
                account_code = mapped_code
            else:
                # Log once and return None
                if account_code not in self._logged_missing_ledgers:
                    frappe.log_error(
                        f"Ledger ID {account_code} not found in mapping",  # noqa: E713
                        "Tegenrekening Mapping",
                    )
                    self._logged_missing_ledgers.add(account_code)
                self._account_cache[account_code] = None
                return None

        # Try by eboekhouden_grootboek_nummer field
        account = frappe.db.get_value(
            "Account", {"company": self.company, "eboekhouden_grootboek_nummer": account_code}, "name"
        )

        if not account:
            # Try by account_number field
            account = frappe.db.get_value(
                "Account", {"company": self.company, "account_number": account_code}, "name"
            )

        if not account:
            # Log missing account code for debugging
            frappe.log_error(
                f"Account code {account_code} not found in company {self.company}",  # noqa: E713
                "Tegenrekening Mapping",
            )

        self._account_cache[account_code] = account
        return account

    def _generate_item_name(self, account_name, account_code):
        """Generate meaningful item name from account name"""
        # Clean up account name
        item_name = account_name
        item_name = item_name.replace(f" - {self.company}", "")
        item_name = item_name.replace(f"{account_code} - ", "")

        # Limit length
        if len(item_name) > 60:
            item_name = item_name[:57] + "..."

        return item_name

    def _get_fallback_item(self, transaction_type, description):
        """Get fallback generic item"""
        if transaction_type == "sales":
            item_code = "EB-GENERIC-INCOME"
            item_name = "Generic Income Item"
            item_group = "Revenue Items"
            account_type = "Income Account"
            # Use specific income account from existing CoA
            fallback_account = "80005 - Donaties - direct op bankrekening - NVV"  # Generic income
        else:
            item_code = "EB-GENERIC-EXPENSE"
            item_name = "Generic Expense Item"
            item_group = "Expense Items"
            account_type = "Expense Account"
            # Use algemene kosten (general expenses) from existing CoA
            fallback_account = "44009 - Onvoorziene kosten - NVV"  # Unforeseen expenses as fallback

        # Ensure fallback item exists
        if not frappe.db.exists("Item", item_code):
            self._create_fallback_item(item_code, item_name, item_group, transaction_type, fallback_account)

        # Get appropriate account - try to find one first, use fallback if not found
        account = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": account_type, "is_group": 0}, "name"
        )

        if not account:
            account = fallback_account

        return {
            "item_code": item_code,
            "item_name": item_name,
            "account": account,
            "item_group": item_group,
            "source": "fallback",
        }

    def _create_fallback_item(self, item_code, item_name, item_group, transaction_type, account=None):
        """Create fallback generic item"""
        try:
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = item_name
            item.item_group = item_group
            item.stock_uom = "Nos"
            item.is_stock_item = 0
            # Always enable both for flexibility
            item.is_sales_item = 1
            item.is_purchase_item = 1

            # Add Item Default if account provided
            if account:
                item.append(
                    "item_defaults",
                    {
                        "company": self.company,
                        "expense_account": account if transaction_type == "purchase" else None,
                        "income_account": account if transaction_type == "sales" else None,
                    },
                )

            item.insert(ignore_permissions=True)
        except Exception:
            pass  # Ignore if already exists


# Helper functions for migration scripts
def get_item_for_purchase_transaction(tegenrekening_code, description="", amount=0):
    """Helper for purchase transactions (invoices, payments)"""
    mapper = SmartTegenrekeningMapper()
    return mapper.get_item_for_tegenrekening(tegenrekening_code, description, "purchase", amount)


def get_item_for_sales_transaction(tegenrekening_code, description="", amount=0):
    """Helper for sales transactions (invoices, receipts)"""
    mapper = SmartTegenrekeningMapper()
    return mapper.get_item_for_tegenrekening(tegenrekening_code, description, "sales", amount)


def create_invoice_line_for_tegenrekening(
    tegenrekening_code, amount, description="", transaction_type="purchase"
):
    """Create complete invoice line dict for a tegenrekening"""
    mapper = SmartTegenrekeningMapper()
    item_mapping = mapper.get_item_for_tegenrekening(
        tegenrekening_code, description, transaction_type, amount
    )

    # Check if mapping was successful
    if not item_mapping or not isinstance(item_mapping, dict):
        frappe.log_error(f"Smart mapping failed for tegenrekening {tegenrekening_code}: {item_mapping}")
        # Return basic fallback
        return {
            "item_code": "E-Boekhouden Import Item",
            "item_name": "E-Boekhouden Import Item",
            "description": description or "E-Boekhouden Import",
            "qty": 1,
            "rate": abs(float(amount)),
            "amount": abs(float(amount)),
        }

    # Get cost center
    cost_center = frappe.db.get_value("Cost Center", {"company": mapper.company, "is_group": 0}, "name")

    line_dict = {
        "item_code": item_mapping.get("item_code"),
        "item_name": item_mapping.get("item_name"),
        "description": description or item_mapping.get("item_name", "Unknown item"),
        "qty": 1,
        "rate": abs(float(amount)),
        "amount": abs(float(amount)),
        "cost_center": cost_center,
    }

    # Add account field based on transaction type
    account = item_mapping.get("account")

    # If no account from mapping, try to get from item defaults
    if not account and item_mapping.get("item_code"):
        item_code = item_mapping.get("item_code")
        if frappe.db.exists("Item", item_code):
            if transaction_type == "sales":
                account = frappe.db.get_value(
                    "Item Default", {"parent": item_code, "company": mapper.company}, "income_account"
                )
            else:
                account = frappe.db.get_value(
                    "Item Default", {"parent": item_code, "company": mapper.company}, "expense_account"
                )

    # Only add account field if we have an account
    if account:
        if transaction_type == "sales":
            line_dict["income_account"] = account
        else:
            line_dict["expense_account"] = account

    return line_dict


@frappe.whitelist()
def test_tegenrekening_mapping():
    """Test the smart tegenrekening mapping system"""
    try:
        response = []
        response.append("=== TESTING SMART TEGENREKENING MAPPING ===")

        mapper = SmartTegenrekeningMapper()

        # Test cases from real E-Boekhouden accounts
        test_cases = [
            ("80001", "Membership contribution", "sales", 50.0),
            ("42200", "Campaign advertising", "purchase", 250.0),
            ("83250", "Event ticket sales", "sales", 25.0),
            ("44007", "Insurance payment", "purchase", 150.0),
            ("99999", "Unknown account", "purchase", 100.0),  # Should create dynamic or fallback
        ]

        for account_code, description, transaction_type, amount in test_cases:
            mapping = mapper.get_item_for_tegenrekening(account_code, description, transaction_type, amount)

            response.append(f"\nAccount: {account_code} ({transaction_type})")
            response.append(f"  Description: {description}")
            response.append(f"  → Item: {mapping['item_code']}")
            response.append(f"  → Name: {mapping['item_name']}")
            response.append(f"  → Account: {mapping['account']}")
            response.append(f"  → Source: {mapping['source']}")

            # Test invoice line creation
            invoice_line = create_invoice_line_for_tegenrekening(
                account_code, amount, description, transaction_type
            )
            response.append(f"  → Invoice line: {invoice_line['item_code']} - €{invoice_line['rate']}")

        return "\n".join(response)

    except Exception as e:
        return f"Error: {e}\n{frappe.get_traceback()}"
