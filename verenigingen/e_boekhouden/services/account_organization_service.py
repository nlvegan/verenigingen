"""
Account Organization Service

Provides services for organizing Chart of Accounts structure according to
Dutch accounting standards, including proper grouping of:
- Vorderingen (Receivables/Debtors)
- Financiële rekeningen (Bank and Cash accounts)
- Schulden (Creditors/Liabilities)
- Belastingen (Tax accounts)
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class AccountOrganizationService:
    """Service for organizing Chart of Accounts structure"""

    def __init__(self, company, settings=None):
        """
        Initialize the service.

        Args:
            company: Company name to organize accounts for
            settings: E-Boekhouden Settings document (optional, will be fetched if not provided)
        """
        self.company = company
        self.settings = settings or frappe.get_single("E-Boekhouden Settings")

        # Get configurable group names from settings
        self.vorderingen_name = self.settings.get("vorderingen_group_name") or "Vorderingen - Receivables"
        self.schulden_name = self.settings.get("schulden_group_name") or "Schulden - Liabilities"
        self.financial_accounts_name = (
            self.settings.get("financial_accounts_group_name") or "Financiële rekeningen - Financial Accounts"
        )
        self.overlopende_activa_name = (
            self.settings.get("overlopende_activa_group_name") or "Overlopende activa - Prepaid Assets"
        )
        self.tax_payable_name = self.settings.get("tax_payable_group_name") or "Belastingen - Taxes Payable"
        self.tax_receivable_name = (
            self.settings.get("tax_receivable_group_name") or "Belastingen - Taxes Receivable"
        )

        # Parse account ranges from settings for organization
        self._parse_account_ranges()

    def _parse_account_ranges(self):
        """Parse account code ranges from settings configuration"""
        # Get asset ranges (should include receivables ranges like 1300-1899)
        asset_ranges_text = self.settings.get("bal_asset_ranges", "")
        self.receivable_ranges = self._extract_receivable_ranges(asset_ranges_text)
        self.financial_account_ranges = self._extract_financial_account_ranges(asset_ranges_text)

        # Get liability ranges (should include creditor ranges like 1600-1699)
        liability_ranges_text = self.settings.get("bal_liability_ranges", "")
        self.creditor_ranges = self._extract_creditor_ranges(liability_ranges_text)

        # Tax ranges are typically hardcoded (15xx for liability tax, 1530 for asset tax)
        # but we could make these configurable in the future
        self.tax_payable_ranges = [("1500", "1529"), ("1531", "1599")]  # Everything except 1530
        self.tax_receivable_account = "1530"

        # Fallback to hardcoded patterns if no configuration found
        if not self.receivable_ranges:
            frappe.logger().warning("No receivable ranges configured, using defaults: 13xx")
            self.receivable_ranges = [("1300", "1399")]

        if not self.creditor_ranges:
            frappe.logger().warning("No creditor ranges configured, using defaults: 16xx, 17xx, 44xx")
            self.creditor_ranges = [("1600", "1699"), ("1700", "1799"), ("4400", "4499")]

        if not self.financial_account_ranges:
            frappe.logger().warning("No financial account ranges configured, using defaults: 10xx-12xx")
            self.financial_account_ranges = [("1000", "1299")]  # Bank and cash accounts

    def _extract_receivable_ranges(self, ranges_text):
        """Extract ranges that indicate receivables/debtors from asset ranges"""
        ranges = []
        if not ranges_text:
            return ranges

        for line in ranges_text.strip().split("\n"):
            line = line.strip()
            if not line or "-" not in line:
                continue

            # Look for lines containing receivable keywords
            if any(keyword in line.lower() for keyword in ["receivable", "vordering", "debtor"]):
                parts = line.split()
                if parts and "-" in parts[0]:
                    range_parts = parts[0].split("-")
                    if len(range_parts) == 2:
                        ranges.append((range_parts[0].strip(), range_parts[1].strip()))

        return ranges

    def _extract_creditor_ranges(self, ranges_text):
        """Extract ranges that indicate creditors/payables from liability ranges"""
        ranges = []
        if not ranges_text:
            return ranges

        for line in ranges_text.strip().split("\n"):
            line = line.strip()
            if not line or "-" not in line:
                continue

            # Look for lines containing creditor keywords
            if any(keyword in line.lower() for keyword in ["creditor", "schuld", "payable"]):
                parts = line.split()
                if parts and "-" in parts[0]:
                    range_parts = parts[0].split("-")
                    if len(range_parts) == 2:
                        ranges.append((range_parts[0].strip(), range_parts[1].strip()))

        return ranges

    def _extract_financial_account_ranges(self, ranges_text):
        """Extract ranges that indicate bank/cash accounts from asset ranges"""
        ranges = []
        if not ranges_text:
            return ranges

        for line in ranges_text.strip().split("\n"):
            line = line.strip()
            if not line or "-" not in line:
                continue

            # Look for lines containing financial account keywords
            if any(keyword in line.lower() for keyword in ["bank", "cash", "liquid", "financ"]):
                parts = line.split()
                if parts and "-" in parts[0]:
                    range_parts = parts[0].split("-")
                    if len(range_parts) == 2:
                        ranges.append((range_parts[0].strip(), range_parts[1].strip()))

        return ranges

    def _is_in_ranges(self, account_code, ranges):
        """Check if an account code falls within any of the configured ranges"""
        if not account_code or not ranges:
            return False

        try:
            # Pad account code for comparison
            account_num = account_code.zfill(4)

            for start, end in ranges:
                start_num = start.zfill(4)
                end_num = end.zfill(4)

                if start_num <= account_num <= end_num:
                    return True

            return False

        except (ValueError, AttributeError):
            return False

    def organize_balance_sheet_accounts(self):
        """
        Organize balance sheet accounts into proper Dutch accounting structure.

        Returns:
            dict: Results including updated accounts, created groups, and errors
        """
        results = {"updated": [], "created_groups": [], "fixed_hierarchy": [], "errors": []}

        try:
            # Ensure group accounts exist
            vorderingen = self._ensure_vorderingen_group()
            if not vorderingen:
                results["errors"].append("Failed to create/find Vorderingen group")
                return results
            results["created_groups"].append(f"Vorderingen: {vorderingen}")

            financial_accounts = self._ensure_financial_accounts_group()
            if not financial_accounts:
                results["errors"].append("Failed to create/find Financial Accounts group")
                return results
            results["created_groups"].append(f"Financial Accounts: {financial_accounts}")

            overlopende_activa = self._ensure_overlopende_activa_group()
            if not overlopende_activa:
                results["errors"].append("Failed to create/find Overlopende activa group")
                return results
            results["created_groups"].append(f"Overlopende activa: {overlopende_activa}")

            schulden = self._ensure_schulden_group()
            if not schulden:
                results["errors"].append("Failed to create/find Schulden group")
                return results
            results["created_groups"].append(f"Schulden: {schulden}")

            belastingen_passiva = self._ensure_tax_payable_group()
            if belastingen_passiva:
                results["created_groups"].append(f"Belastingen (Passiva): {belastingen_passiva}")

            belastingen_activa = self._ensure_tax_receivable_group()
            if belastingen_activa:
                results["created_groups"].append(f"Belastingen (Activa): {belastingen_activa}")

            # Move accounts to proper groups
            self._organize_debtor_accounts(vorderingen, results)
            self._organize_financial_accounts(financial_accounts, results)
            self._organize_overlopende_activa_accounts(overlopende_activa, results)
            self._organize_creditor_accounts(schulden, results)

            if belastingen_passiva:
                self._organize_tax_payable_accounts(belastingen_passiva, results)

            if belastingen_activa:
                self._organize_tax_receivable_accounts(belastingen_activa, results)

            frappe.db.commit()

            return results

        except Exception as e:
            frappe.log_error(
                title="Account Organization Error", message=f"{str(e)}\n{frappe.get_traceback()}"
            )
            results["errors"].append(str(e))
            return results

    def _ensure_vorderingen_group(self):
        """Ensure Vorderingen (Receivables) group exists under Activa"""
        # Look for existing Vorderingen group
        existing = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_number": "4", "is_group": 1, "root_type": "Asset"},
            "name",
        )

        if existing:
            # Ensure it's under Activa, not a root account
            parent = frappe.db.get_value("Account", existing, "parent_account")
            if not parent:
                activa = self._get_activa_root()
                if activa:
                    frappe.db.set_value("Account", existing, "parent_account", activa)
                    frappe.logger().info(f"Moved Vorderingen under Activa: {existing}")
            return existing

        return self._create_group_account(
            group_name=self.vorderingen_name,
            root_type="Asset",
            account_number="4",
            parent_account=self._get_activa_root(),
        )

    def _ensure_financial_accounts_group(self):
        """Ensure Financial Accounts (Bank/Cash) group exists under Activa"""
        search_name = self.financial_accounts_name.split(" - ")[0]

        # Look for existing Financial Accounts group
        existing = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", f"%{search_name}%"],
                "is_group": 1,
                "root_type": "Asset",
            },
            "name",
        )

        if existing:
            # Ensure it's directly under Activa
            parent = frappe.db.get_value("Account", existing, "parent_account")
            activa = self._get_activa_root()
            if parent != activa and activa:
                frappe.db.set_value("Account", existing, "parent_account", activa)
                frappe.logger().info(f"Moved {self.financial_accounts_name} under Activa: {existing}")
            return existing

        return self._create_group_account(
            group_name=self.financial_accounts_name,
            root_type="Asset",
            account_number=None,
            parent_account=self._get_activa_root(),
        )

    def _ensure_overlopende_activa_group(self):
        """Ensure Overlopende activa (Prepaid/Accrued Assets) group exists under Activa"""
        search_name = self.overlopende_activa_name.split(" - ")[0]

        # Look for existing Overlopende activa group
        existing = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", f"%{search_name}%"],
                "is_group": 1,
                "root_type": "Asset",
            },
            "name",
        )

        if existing:
            # Ensure it's directly under Activa
            parent = frappe.db.get_value("Account", existing, "parent_account")
            activa = self._get_activa_root()
            if parent != activa and activa:
                frappe.db.set_value("Account", existing, "parent_account", activa)
                frappe.logger().info(f"Moved {self.overlopende_activa_name} under Activa: {existing}")
            return existing

        return self._create_group_account(
            group_name=self.overlopende_activa_name,
            root_type="Asset",
            account_number="15",
            parent_account=self._get_activa_root(),
        )

    def _ensure_schulden_group(self):
        """Ensure Schulden (Creditors) group exists under Passiva"""
        # Extract base name for search (e.g., "Schulden" from "Schulden - Liabilities")
        search_name = self.schulden_name.split(" - ")[0]

        # Look for existing Schulden group
        existing = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", f"%{search_name}%"],
                "is_group": 1,
                "root_type": "Liability",
            },
            "name",
        )

        if existing:
            return existing

        return self._create_group_account(
            group_name=self.schulden_name,
            root_type="Liability",
            account_number=None,
            parent_account=self._get_passiva_root(),
        )

    def _ensure_tax_payable_group(self):
        """Ensure Belastingen (Tax Payable) group exists under Passiva"""
        search_name = self.tax_payable_name.split(" - ")[0]

        existing = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", f"%{search_name}%"],
                "is_group": 1,
                "root_type": "Liability",
            },
            "name",
        )

        if existing:
            # Ensure it's directly under Passiva
            parent = frappe.db.get_value("Account", existing, "parent_account")
            passiva = self._get_passiva_root()
            if parent != passiva and passiva:
                frappe.db.set_value("Account", existing, "parent_account", passiva)
                frappe.logger().info(f"Moved {self.tax_payable_name} under Passiva: {existing}")
            return existing

        return self._create_group_account(
            group_name=self.tax_payable_name,
            root_type="Liability",
            account_number=None,
            parent_account=self._get_passiva_root(),
        )

    def _ensure_tax_receivable_group(self):
        """Ensure Belastingen (Tax Receivable) group exists under Activa"""
        search_name = self.tax_receivable_name.split(" - ")[0]

        existing = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", f"%{search_name}%"],
                "is_group": 1,
                "root_type": "Asset",
            },
            "name",
        )

        if existing:
            # Ensure it's directly under Activa
            parent = frappe.db.get_value("Account", existing, "parent_account")
            activa = self._get_activa_root()
            if parent != activa and activa:
                frappe.db.set_value("Account", existing, "parent_account", activa)
                frappe.logger().info(f"Moved {self.tax_receivable_name} under Activa: {existing}")
            return existing

        return self._create_group_account(
            group_name=self.tax_receivable_name,
            root_type="Asset",
            account_number=None,
            parent_account=self._get_activa_root(),
        )

    def _organize_debtor_accounts(self, vorderingen_group, results):
        """Move debtor accounts under Vorderingen based on configured ranges"""
        # Get all non-group asset accounts
        all_accounts = frappe.db.get_all(
            "Account",
            filters={"company": self.company, "root_type": "Asset", "is_group": 0},
            fields=["name", "account_number", "parent_account"],
        )

        # Check each account against receivable ranges
        for account in all_accounts:
            account_code = account.account_number
            if not account_code:
                continue

            # Check if account falls within any receivable range
            if self._is_in_ranges(account_code, self.receivable_ranges):
                if account.parent_account != vorderingen_group:
                    frappe.db.set_value("Account", account.name, "parent_account", vorderingen_group)
                    results["updated"].append(f"{account.account_number} → Vorderingen")
                    frappe.logger().info(f"Moved {account.name} to Vorderingen")

    def _organize_financial_accounts(self, financial_group, results):
        """Move bank and cash accounts under Financial Accounts based on configured ranges"""
        # Get all non-group asset accounts
        all_accounts = frappe.db.get_all(
            "Account",
            filters={"company": self.company, "root_type": "Asset", "is_group": 0},
            fields=["name", "account_number", "parent_account"],
        )

        # Check each account against financial account ranges
        for account in all_accounts:
            account_code = account.account_number
            if not account_code:
                continue

            # Check if account falls within any financial account range
            if self._is_in_ranges(account_code, self.financial_account_ranges):
                if account.parent_account != financial_group:
                    frappe.db.set_value("Account", account.name, "parent_account", financial_group)
                    results["updated"].append(f"{account.account_number} → Financial Accounts")
                    frappe.logger().info(f"Moved {account.name} to Financial Accounts")

    def _organize_overlopende_activa_accounts(self, overlopende_group, results):
        """Move prepaid/accrued asset accounts (1480, 1600) under Overlopende activa"""
        # Specific accounts that should be under Overlopende activa
        prepaid_account_numbers = ["1480", "1600"]

        prepaid_accounts = frappe.db.get_all(
            "Account",
            filters={
                "company": self.company,
                "account_number": ["in", prepaid_account_numbers],
                "root_type": "Asset",
                "is_group": 0,
            },
            fields=["name", "account_number", "account_name", "parent_account"],
        )

        for account in prepaid_accounts:
            if account.parent_account != overlopende_group:
                frappe.db.set_value("Account", account.name, "parent_account", overlopende_group)
                results["updated"].append(
                    f"{account.account_number} - {account.account_name} → Overlopende activa"
                )
                frappe.logger().info(f"Moved {account.name} to Overlopende activa")

    def _organize_creditor_accounts(self, schulden_group, results):
        """Move creditor accounts under Schulden based on configured ranges"""
        # Get all non-group liability accounts
        all_accounts = frappe.db.get_all(
            "Account",
            filters={"company": self.company, "root_type": "Liability", "is_group": 0},
            fields=["name", "account_number", "parent_account"],
        )

        # Check each account against creditor ranges
        for account in all_accounts:
            account_code = account.account_number
            if not account_code:
                continue

            # Check if account falls within any creditor range
            if self._is_in_ranges(account_code, self.creditor_ranges):
                if account.parent_account != schulden_group:
                    frappe.db.set_value("Account", account.name, "parent_account", schulden_group)
                    results["updated"].append(f"{account.account_number} → Schulden")
                    frappe.logger().info(f"Moved {account.name} to Schulden")

    def _organize_tax_payable_accounts(self, tax_group, results):
        """Move tax payable accounts (150x except 1530) under Belastingen (Passiva)"""
        tax_accounts = frappe.db.get_all(
            "Account",
            filters={
                "company": self.company,
                "account_number": ["like", "15%"],
                "root_type": "Liability",
                "is_group": 0,
            },
            fields=["name", "account_number", "parent_account"],
        )

        for account in tax_accounts:
            # Skip 1530 - that's a receivable
            if account.account_number == "1530":
                continue

            if account.parent_account != tax_group:
                frappe.db.set_value("Account", account.name, "parent_account", tax_group)
                results["updated"].append(f"{account.account_number} → Belastingen (Passiva)")
                frappe.logger().info(f"Moved {account.name} to Belastingen (Passiva)")

    def _organize_tax_receivable_accounts(self, tax_group, results):
        """Move tax receivable accounts (1530) under Belastingen (Activa)"""
        tax_accounts = frappe.db.get_all(
            "Account",
            filters={"company": self.company, "account_number": "1530", "root_type": "Asset", "is_group": 0},
            fields=["name", "account_number", "parent_account"],
        )

        for account in tax_accounts:
            if account.parent_account != tax_group:
                frappe.db.set_value("Account", account.name, "parent_account", tax_group)
                results["updated"].append(f"{account.account_number} → Belastingen (Activa)")
                frappe.logger().info(f"Moved {account.name} to Belastingen (Activa)")

    def _get_activa_root(self):
        """Get the Activa (Asset) root account"""
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Asset", "account_number": "0", "is_group": 1},
            "name",
        )

    def _get_passiva_root(self):
        """Get the Passiva (Liability) root account"""
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Liability", "account_number": "3", "is_group": 1},
            "name",
        )

    def _create_group_account(self, group_name, root_type, account_number, parent_account):
        """
        Create a group account.

        Args:
            group_name: Name for the group account
            root_type: ERPNext root type (Asset, Liability, etc.)
            account_number: Account number (can be None)
            parent_account: Parent account name

        Returns:
            str: Name of created account, or None if failed
        """
        if not parent_account:
            frappe.logger().error(f"No parent account found for {group_name}")
            return None

        try:
            group_acc = frappe.new_doc("Account")
            group_acc.account_name = group_name
            if account_number:
                group_acc.account_number = account_number
            group_acc.company = self.company
            group_acc.parent_account = parent_account
            group_acc.root_type = root_type
            group_acc.is_group = 1
            group_acc.insert(ignore_permissions=True)

            frappe.logger().info(f"Created group account: {group_acc.name} under {parent_account}")
            return group_acc.name

        except Exception as e:
            frappe.logger().error(f"Failed to create {group_name}: {str(e)}")
            return None


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def organize_balance_sheet_accounts(company=None):
    """
    API endpoint to organize balance sheet accounts.

    Args:
        company: Company name (optional, uses default from settings if not provided)

    Returns:
        dict: Results of the organization operation
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        return {"success": False, "error": "No company specified"}

    service = AccountOrganizationService(company)
    results = service.organize_balance_sheet_accounts()

    return {
        "success": len(results.get("errors", [])) == 0,
        "message": f"Updated {len(results.get('updated', []))} accounts",
        "details": results,
    }
