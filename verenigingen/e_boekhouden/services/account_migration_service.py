# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Account Migration Service

Centralized account creation and hierarchy management for E-Boekhouden migrations.
Extracted from e_boekhouden_migration.py to reduce controller size.
"""

from typing import Callable, Dict, List, Optional, Set

import frappe

from verenigingen.e_boekhouden.utils.security_helper import validate_and_insert, validate_and_save


class AccountMigrationService:
    """
    Service for creating and organizing ERPNext accounts from E-Boekhouden data.

    Handles:
    - Root account creation (Dutch COA structure)
    - Account hierarchy management
    - Parent account finding with Dutch naming conventions
    - Bank account creation for COA bank accounts
    """

    def __init__(
        self,
        company: str,
        settings=None,
        error_callback: Optional[Callable] = None,
        account_group_mappings: Optional[Dict[str, str]] = None,
        group_accounts: Optional[Set[str]] = None,
    ):
        """
        Initialize the account migration service.

        Args:
            company: Company name for account creation
            settings: E-Boekhouden Settings doc (fetched if not provided)
            error_callback: Function to call for error logging (signature: message, record_type, record_data)
            account_group_mappings: Dict mapping group codes to group names
            group_accounts: Set of account codes that should be created as groups
        """
        self.company = company
        self._settings = settings
        self._error_callback = error_callback
        self._account_group_mappings = account_group_mappings or {}
        self._group_accounts = group_accounts or set()

    @property
    def settings(self):
        """Lazy-load E-Boekhouden Settings."""
        if self._settings is None:
            self._settings = frappe.get_single("E-Boekhouden Settings")
        return self._settings

    def log_error(self, message: str, record_type: str = None, record_data: dict = None):
        """Log error using callback or frappe.log_error."""
        if self._error_callback:
            self._error_callback(message, record_type, record_data)
        else:
            frappe.log_error(message, f"E-Boekhouden {record_type or 'Account'} Error")

    def ensure_root_accounts(self) -> dict:
        """Ensure root accounts exist based on E-boekhouden categories and Dutch accounting standards."""
        try:
            if not self.company:
                return {"success": False, "error": "No company set"}

            # Define root accounts based on E-boekhouden categories and Dutch standards
            root_accounts = [
                # Main root categories matching E-boekhouden structure
                {"account_name": "Activa", "root_type": "Asset", "account_number": "0", "category": "BAL"},
                {
                    "account_name": "Passiva",
                    "root_type": "Liability",
                    "account_number": "3",
                    "category": "BAL",
                },
                {
                    "account_name": "Eigen Vermogen",
                    "root_type": "Equity",
                    "account_number": "5",
                    "category": "BAL",
                },
                {
                    "account_name": "Opbrengsten",
                    "root_type": "Income",
                    "account_number": "8",
                    "category": "VW",
                },
                {"account_name": "Kosten", "root_type": "Expense", "account_number": "6", "category": "VW"},
            ]

            created = []
            errors = []
            existing = []

            for acc in root_accounts:
                try:
                    # Check if a root account of this type already exists
                    existing_account = frappe.db.get_value(
                        "Account",
                        {
                            "company": self.company,
                            "root_type": acc["root_type"],
                            "parent_account": ["in", ["", None]],
                            "is_group": 1,
                        },
                        "name",
                    )

                    if existing_account:
                        existing.append(f"{acc['account_name']} ({existing_account})")
                        frappe.logger().info(
                            f"Root account for {acc['root_type']} already exists: {existing_account}"
                        )
                        continue

                    # Try to create root account using ERPNext's account creation method
                    # This bypasses the parent_account requirement for true root accounts
                    account = frappe.new_doc("Account")
                    account.account_name = acc["account_name"]
                    account.company = self.company
                    account.root_type = acc["root_type"]
                    account.is_group = 1
                    account.account_number = acc["account_number"]

                    # Use special validation flags for root accounts
                    account.flags.ignore_validate = True
                    account.flags.ignore_mandatory = True

                    # Try multiple creation methods with proper permissions
                    try:
                        validate_and_save(
                            account, skip_validation=True
                        )  # Root accounts need special handling
                        created.append(f"{acc['account_name']} ({acc['root_type']})")
                        frappe.logger().info(f"Created root account: {account.name}")
                    except Exception:
                        # If save fails, try insert
                        try:
                            validate_and_insert(
                                account, skip_validation=True
                            )  # Root accounts need special handling
                            created.append(f"{acc['account_name']} ({acc['root_type']})")
                            frappe.logger().info(f"Created root account via insert: {account.name}")
                        except Exception as e2:
                            errors.append(f"{acc['account_name']}: {str(e2)}")
                            frappe.logger().error(
                                f"Failed to create root account {acc['account_name']}: {str(e2)}"
                            )

                except Exception as e:
                    errors.append(f"{acc['account_name']}: {str(e)}")
                    frappe.logger().error(f"Error processing root account {acc['account_name']}: {str(e)}")

            # If no accounts were created or existed, this indicates a fundamental issue
            total_available = len(created) + len(existing)
            if total_available == 0:
                return {
                    "success": False,
                    "error": "No root accounts available - this will cause Chart of Accounts import to fail",
                    "details": {"created": created, "existing": existing, "errors": errors},
                }

            # Commit any successful creations
            if created:
                frappe.db.commit()

            return {
                "success": True,
                "created": created,
                "existing": existing,
                "errors": errors,
                "message": f"Root accounts ready: {len(created)} created, {len(existing)} existing, {len(errors)} errors",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_account(self, account_data: dict, use_enhanced: bool = False) -> bool:
        """Create Account in ERPNext."""
        try:
            # Use enhanced migration if available and enabled
            if use_enhanced:
                try:
                    from verenigingen.e_boekhouden.utils.eboekhouden_migration_enhancements import (
                        EnhancedAccountMigration,
                    )

                    # Create a minimal migration-like object for enhanced migrator
                    class MigrationProxy:
                        def __init__(proxy_self, service):
                            proxy_self.company = service.company
                            proxy_self._account_group_mappings = service._account_group_mappings
                            proxy_self._group_accounts = service._group_accounts

                        def log_error(proxy_self, msg, rt=None, rd=None):
                            service.log_error(msg, rt, rd)

                    enhanced_migrator = EnhancedAccountMigration(MigrationProxy(self))
                    result = enhanced_migrator.analyze_and_create_account(account_data)

                    account_code = account_data.get("code", "")
                    account_name = account_data.get("description", "")

                    if result["status"] == "created":
                        frappe.logger().info(
                            f"Created account: {account_code} - {account_name} (Group: {result.get('group', 'N/A')})"
                        )
                        return True
                    elif result["status"] == "skipped":
                        frappe.logger().info(
                            f"Skipped: {account_code} - {account_name} ({result.get('reason', '')})"
                        )
                        return False
                    else:
                        self.log_error(f"Failed: {account_code} - {account_name}: {result.get('error', '')}")
                        return False
                except ImportError:
                    # Fall back to standard migration
                    pass

            # Standard migration logic
            # Map e-Boekhouden account to ERPNext account
            account_code = account_data.get("code", "")
            account_name = account_data.get("description", "")
            category = account_data.get("category", "")
            group_code = account_data.get("group", "")

            if not account_code or not account_name:
                self.log_error(f"Invalid account data: code={account_code}, name={account_name}")
                return False

            # Clean up account name - remove duplicate account code if present
            # E-Boekhouden sometimes includes the code in the name like "88210 - 88210 - Advertenties in vm"
            if account_name.startswith(f"{account_code} - "):
                # Remove the first occurrence of "code - "
                account_name = account_name[len(account_code) + 3 :]

            # Also check if the name starts with just the code (without dash)
            if account_name.startswith(account_code):
                account_name = account_name[len(account_code) :].lstrip(" -")

            # If account name is empty after cleaning, use a default
            if not account_name.strip():
                account_name = f"Account {account_code}"

            # Truncate account name if too long (ERPNext limit is 140 chars)
            if len(account_name) > 120:  # Leave room for account code
                account_name = account_name[:120] + "..."
                frappe.logger().info(f"Truncated long account name for {account_code}")

            # Use the cleaned account name without the code
            full_account_name = account_name
            if len(full_account_name) > 140:
                # If too long, truncate
                full_account_name = account_name[:137] + "..."

            # CACHE SETTINGS - Fetch once and reuse throughout method to avoid redundant DB queries
            settings = self.settings
            # Note: classification_rules loaded but used via AccountClassificationService

            # Use company from service
            company = self.company
            if not company:
                company = settings.default_company
                if company:
                    frappe.logger().warning(f"Service has no company set, using default company: {company}")

            if not company:
                self.log_error("No company set on service or in E-Boekhouden Settings")
                return False

            # Check if account already exists
            # Check both by account_number and by name (which includes company suffix)
            existing_by_number = frappe.db.exists(
                "Account", {"account_number": account_code, "company": company}
            )

            # Get company abbreviation
            company_abbr = frappe.db.get_value("Company", company, "abbr")
            existing_by_name = frappe.db.exists("Account", {"name": f"{full_account_name} - {company_abbr}"})

            if existing_by_number or existing_by_name:
                frappe.logger().info(
                    f"SKIPPING - Account {account_code} already exists (by_number={existing_by_number}, by_name={existing_by_name})"
                )
                return False

            # CLASSIFICATION: Use AccountClassificationService
            # This service implements the same priority-based logic that was previously inline
            try:
                from verenigingen.e_boekhouden.services.account_classification_service import (
                    AccountClassificationService,
                )

                service = AccountClassificationService(settings=settings)
                classification_result = service.classify_account(account_data)

                account_type = classification_result.account_type
                root_type = classification_result.root_type

                frappe.logger().info(
                    f"CLASSIFIED - {account_code}: {account_type}/{root_type} "
                    f"(Confidence: {classification_result.confidence.value}, Strategy: {classification_result.strategy_used})"
                )

                if classification_result.notes:
                    frappe.logger().debug(f"  Notes: {classification_result.notes}")

            except Exception as e:
                frappe.log_error(
                    f"Account classification failed for {account_code} ({account_name}): {str(e)}\n"
                    f"Category: {category}, Group: {group_code}",
                    "Account Classification Error",
                )
                # Fallback: Try to make an educated guess based on account code
                if account_code.startswith(("8", "9")):
                    account_type = "Income Account"
                    root_type = "Income"
                elif account_code.startswith(("4", "6", "7")):
                    account_type = "Expense Account"
                    root_type = "Expense"
                else:
                    account_type = "Current Asset"
                    root_type = "Asset"
                frappe.logger().warning(
                    f"Using fallback classification for {account_code}: {account_type}/{root_type}"
                )

            # Check if this should be a root account
            # With our Dutch root account structure in place, very few accounts should be truly root
            is_root_account = False
            parent_account = None

            # IMPORTANT: We now have Dutch root accounts (Activa, Passiva, Eigen Vermogen, Opbrengsten, Kosten)
            # Only treat accounts as root if they are truly meant to be at the top level
            # Most E-boekhouden accounts should be children of these root accounts

            frappe.logger().info(
                f"Analyzing account {account_code}: len={len(account_code)}, group={group_code}, category={category}"
            )

            # Very restrictive root account logic - only truly top-level accounts
            if len(account_code) == 1 or (  # Single digit codes like "0", "3", "5", "6", "8"
                len(account_code) == 2 and account_code in ["00", "30", "50", "60", "80"]
            ):  # Very specific two-digit roots
                is_root_account = True
                frappe.logger().info(
                    f"Account {account_code} identified as ROOT account (single digit or specific two-digit)"
                )
            else:
                # All other accounts should find appropriate parents from our root structure
                # This includes accounts with group codes like 001-010 - they should be children, not roots
                frappe.logger().info(f"Account {account_code} will be child account (not root)")

            # For all non-root accounts, find appropriate parent from our Dutch root structure
            if not is_root_account:
                # Check if this account has a group code and if we have a mapping for it
                if group_code and self._account_group_mappings and group_code in self._account_group_mappings:
                    # Try to find or create the intermediate group account
                    parent_account = self.get_or_create_group_account(group_code, root_type, company)
                else:
                    # Use standard parent account logic
                    parent_account = self.get_parent_account(account_type, root_type, company)

                # If no specific parent found, ensure we at least get the appropriate root account
                if not parent_account:
                    # Find the appropriate Dutch root account based on root_type
                    parent_account = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "root_type": root_type,
                            "is_group": 1,
                            "parent_account": ["in", ["", None]],
                        },
                        "name",
                    )

                    if parent_account:
                        frappe.logger().info(
                            f"Using Dutch root account as parent for {account_code}: {parent_account}"
                        )
                    else:
                        frappe.logger().warning(
                            f"No Dutch root account found for {account_code} with root_type {root_type}"
                        )
                        return False  # Skip account if no parent can be found

            # Determine if this should be a group account
            is_group = 0

            # Check if this account was identified as a group
            if self._group_accounts and account_code in self._group_accounts:
                is_group = 1
                frappe.logger().info(f"Creating account {account_code} as group (has children)")
            elif is_root_account:
                # Root accounts must be groups in ERPNext
                is_group = 1
                frappe.logger().info(f"Creating root account {account_code} as group")

            # Create new account
            account_doc = {
                "doctype": "Account",
                "account_name": full_account_name,  # Use the properly formatted name
                "account_number": account_code,
                "eboekhouden_grootboek_nummer": account_code,  # Also populate E-boekhouden field
                "company": company,
                "root_type": root_type,
                "is_group": is_group,
                "disabled": 0,
            }

            # Only set parent_account if one was found
            if parent_account:
                account_doc["parent_account"] = parent_account

            # Only set account_type if it's not empty (some accounts don't need a specific type)
            if account_type:
                account_doc["account_type"] = account_type

            account = frappe.get_doc(account_doc)

            frappe.logger().info(
                f"Attempting to create account: {account_code} - {account_name}, is_group={is_group}, parent={parent_account}, root_type={root_type}"
            )

            validate_and_insert(account)
            frappe.logger().info(f"Successfully created account: {account_code} - {account_name}")

            # If this is a bank account, try to create corresponding Bank Account record
            if account_type == "Bank":
                try:
                    self.create_bank_account_for_coa_account(account, account_name)
                except Exception as e:
                    frappe.logger().error(f"Failed to create Bank Account for {account_code}: {str(e)}")
                    # Don't fail the entire account creation if bank account creation fails

            return True

        except Exception as e:
            # account_code might not be defined if error occurs early
            account_ref = account_data.get("code", "Unknown") if account_data else "Unknown"
            self.log_error(
                f"Failed to create account {account_ref}: {str(e)}",
                "account",
                account_data if account_data else {},
            )
            return False

    def create_bank_account_for_coa_account(self, account_doc, account_name: str):
        """Enhanced Bank Account creation for Chart of Accounts bank account."""
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_coa_import import (
                create_bank_account_record,
                extract_bank_info_from_account_name,
                get_or_create_bank,
                is_potential_bank_account,
            )

            # First check if this looks like a bank account
            account_code = getattr(account_doc, "account_number", None)
            if not is_potential_bank_account(account_name, account_code):
                frappe.logger().debug(f"Account {account_name} does not appear to be a bank account")
                return None

            # Extract bank information from account name
            bank_info = extract_bank_info_from_account_name(account_name)

            # Enhanced validation - accept accounts even without perfect number match
            if bank_info.get("account_number") or bank_info.get("bank_name") != "Unknown Bank":
                # Check if Bank Account already exists
                existing_bank_account = None
                if bank_info.get("iban"):
                    existing_bank_account = frappe.db.exists("Bank Account", {"iban": bank_info["iban"]})

                if not existing_bank_account and bank_info.get("account_number"):
                    existing_bank_account = frappe.db.exists(
                        "Bank Account", {"bank_account_no": bank_info["account_number"]}
                    )

                # Also check by account mapping to avoid duplicates
                if not existing_bank_account:
                    existing_bank_account = frappe.db.exists("Bank Account", {"account": account_doc.name})

                if not existing_bank_account:
                    # Create or get Bank record
                    bank_name = get_or_create_bank(bank_info)

                    # Create Bank Account record with enhanced validation
                    bank_account = create_bank_account_record(
                        account=account_doc,
                        bank_name=bank_name,
                        bank_info=bank_info,
                        company=account_doc.company,
                    )

                    if bank_account:
                        frappe.logger().info(
                            f"Created Bank Account: {bank_account} for account: {account_doc.name}"
                        )
                        return bank_account
                    else:
                        frappe.logger().warning(f"Failed to create Bank Account for {account_doc.name}")
                else:
                    frappe.logger().info(f"Bank Account already exists for account: {account_name}")
            else:
                frappe.logger().debug(f"Insufficient bank info extracted from {account_name}: {bank_info}")

            return None

        except Exception as e:
            frappe.logger().error(f"Error creating bank account for {account_doc.name}: {str(e)}")
            frappe.log_error(
                f"Bank account creation error for {account_doc.name}: {str(e)}", "Bank Account Creation"
            )
            return None

    def get_parent_account(self, account_type: str, root_type: str, company: str = None) -> Optional[str]:
        """Get appropriate parent account for the new account with enhanced logic."""
        company = company or self.company
        try:
            # Enhanced parent account finding logic
            parent = None

            # First, try to find existing parent accounts by type
            if account_type == "Tax":
                # Look for Tax Assets or Duties and Taxes - try multiple variations
                tax_parent_names = [
                    "Tax Assets",
                    "Duties and Taxes",
                    "VAT",
                    "BTW",
                    "Belastingen",
                    "Current Liabilities",
                    "Schulden op korte termijn",
                ]

                for parent_name in tax_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {"company": company, "account_name": ["like", f"%{parent_name}%"], "is_group": 1},
                        "name",
                    )
                    if parent:
                        break

            elif account_type == "Bank":
                # Look for Bank group accounts, prioritizing E-Boekhouden specific names
                bank_parent_names = ["Liquide middelen", "Bank", "Kas en Bank", "Financiele activa"]

                for parent_name in bank_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Asset",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Bank parent account: {parent} for {parent_name}")
                        break

                # If no specific bank group, try by account type
                if not parent:
                    parent = frappe.db.get_value(
                        "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
                    )

            elif account_type == "Cash":
                # Look for Cash group accounts, prioritizing shared liquide middelen group
                cash_parent_names = ["Liquide middelen", "Kas", "Cash"]

                for parent_name in cash_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Asset",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Cash parent account: {parent} for {parent_name}")
                        break

                # If no specific cash group, try by account type
                if not parent:
                    parent = frappe.db.get_value(
                        "Account", {"company": company, "account_type": "Cash", "is_group": 1}, "name"
                    )

            elif account_type == "Income Account":
                # Look for Income/Opbrengsten/Inkomsten group accounts
                income_parent_names = ["Inkomsten", "Opbrengsten", "Direct Income", "Income"]

                for parent_name in income_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Income",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Income parent account: {parent} for {parent_name}")
                        break

            elif account_type == "Expense Account":
                # Look for Expense/Kosten group accounts
                expense_parent_names = ["Kosten", "Uitgaven", "Direct Expenses", "Expenses"]

                for parent_name in expense_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Expense",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Expense parent account: {parent} for {parent_name}")
                        break

            elif root_type == "Equity":
                # Handle Equity accounts (which have empty account_type)
                # Look for Equity/Eigen Vermogen group accounts
                equity_parent_names = ["Eigen Vermogen", "Equity", "Capital"]

                for parent_name in equity_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Equity",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Equity parent account: {parent} for {parent_name}")
                        break

            # If still no parent found, use enhanced fallback logic
            if not parent:
                # Try to find or create appropriate group accounts based on root_type
                parent = self.find_or_create_parent_group(root_type, company)

            # Final fallback: get the root account for this root_type
            if not parent:
                parent = frappe.db.get_value(
                    "Account",
                    {
                        "company": company,
                        "root_type": root_type,
                        "is_group": 1,
                        "parent_account": ["in", ["", None]],
                    },
                    "name",
                )

            return parent

        except Exception as e:
            self.log_error(f"Error finding parent account for {account_type}/{root_type}: {str(e)}")
            # Return any group account as last resort
            return frappe.db.get_value("Account", {"company": company, "is_group": 1}, "name", order_by="lft")

    def get_or_create_group_account(
        self, group_code: str, root_type: str, company: str = None
    ) -> Optional[str]:
        """Find or create an intermediate group account based on group mapping."""
        company = company or self.company
        try:
            if not self._account_group_mappings or group_code not in self._account_group_mappings:
                return None

            group_name = self._account_group_mappings[group_code]

            # Check if group account already exists
            existing_group = frappe.db.get_value(
                "Account",
                {"account_name": group_name, "company": company, "is_group": 1, "root_type": root_type},
                "name",
            )

            if existing_group:
                frappe.logger().info(f"Found existing group account for {group_code}: {existing_group}")
                return existing_group

            # Find the appropriate root account to be parent of this group
            root_parent_result = frappe.db.sql(
                """
                SELECT name
                FROM `tabAccount`
                WHERE company = %s
                AND root_type = %s
                AND is_group = 1
                AND (parent_account IS NULL OR parent_account = '')
                LIMIT 1
            """,
                (company, root_type),
            )

            root_parent = root_parent_result[0][0] if root_parent_result else None

            if not root_parent:
                frappe.logger().warning(
                    f"No root account found for group {group_code} with root_type {root_type}"
                )
                return None

            # Create the group account
            group_account = frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": group_name,
                    "company": company,
                    "root_type": root_type,
                    "is_group": 1,
                    "parent_account": root_parent,
                    "disabled": 0,
                }
            )

            validate_and_insert(group_account)
            frappe.logger().info(f"Created group account: {group_code} - {group_name} under {root_parent}")

            return group_account.name

        except Exception as e:
            frappe.logger().error(f"Error creating group account for {group_code}: {str(e)}")
            return None

    def find_or_create_parent_group(self, root_type: str, company: str = None) -> Optional[str]:
        """Find or create appropriate parent group account."""
        company = company or self.company
        try:
            # Define parent group mappings for each root type
            parent_group_mappings = {
                "Asset": ["Current Assets", "Vlottende activa", "Activa"],
                "Liability": ["Current Liabilities", "Schulden op korte termijn", "Passiva"],
                "Equity": ["Capital Account", "Eigen vermogen", "Kapitaal"],
                "Income": ["Direct Income", "Opbrengsten", "Inkomsten"],
                "Expense": ["Direct Expenses", "Kosten", "Uitgaven"],
            }

            # Try to find existing parent group
            potential_parents = parent_group_mappings.get(root_type, [])

            for parent_name in potential_parents:
                parent = frappe.db.get_value(
                    "Account",
                    {
                        "company": company,
                        "account_name": ["like", f"%{parent_name}%"],
                        "root_type": root_type,
                        "is_group": 1,
                    },
                    "name",
                )
                if parent:
                    return parent

            # If no specific parent found, look for any group under this root_type
            parent_accounts = frappe.db.get_all(
                "Account",
                {"company": company, "root_type": root_type, "is_group": 1},
                ["name", "parent_account"],
                order_by="lft",
            )

            # Return the first non-root group account
            for acc in parent_accounts:
                if acc.parent_account:  # Not a root account
                    return acc.name

            # If only root accounts exist, return the root
            if parent_accounts:
                return parent_accounts[0].name

            return None

        except Exception as e:
            frappe.logger().error(f"Error in find_or_create_parent_group: {str(e)}")
            return None
