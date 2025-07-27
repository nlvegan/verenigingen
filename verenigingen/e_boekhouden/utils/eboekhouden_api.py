"""
E-Boekhouden API Integration Utilities

This module provides utilities for integrating with the e-Boekhouden.nl API
for migrating accounting data to ERPNext.
"""

import json
import xml.etree.ElementTree as ET

import frappe
import requests


class EBoekhoudenAPI:
    """E-Boekhouden API client"""

    def __init__(self, settings=None):
        """Initialize API client with settings"""
        if not settings:
            settings = frappe.get_single("E-Boekhouden Settings")

        self.settings = settings

        # Ensure API URL has proper scheme
        api_url = settings.api_url.rstrip("/")  # Remove trailing slash
        if not api_url.startswith(("http://", "https://")):
            # Default to https if no scheme provided
            api_url = f"https://{api_url}"
        self.base_url = api_url

        self.api_token = settings.get_password("api_token")
        self.source = settings.source_application or "Verenigingen ERPNext"

        # Validate required settings
        if not self.base_url or self.base_url == "https://":
            raise ValueError("E-Boekhouden API URL is not configured")
        if not self.api_token:
            raise ValueError("E-Boekhouden API token is not configured")

    def get_session_token(self):
        """Get session token using API token"""
        try:
            session_url = f"{self.base_url}/v1/session"
            session_data = {"accessToken": self.api_token, "source": self.source}

            frappe.logger().debug(f"Requesting session token from: {session_url}")
            response = requests.post(session_url, json=session_data, timeout=30)

            if response.status_code == 200:
                session_response = response.json()
                return session_response.get("token")
            else:
                error_msg = f"Session token request failed: {response.status_code} - {response.text}"
                frappe.log_error(error_msg, "E-Boekhouden API")
                frappe.msgprint(error_msg, title="E-Boekhouden API Error", indicator="red")
                return None

        except Exception as e:
            error_msg = f"Error getting session token from {self.base_url}: {str(e)}"
            frappe.log_error(error_msg, "E-Boekhouden API")
            frappe.msgprint(error_msg, title="E-Boekhouden API Error", indicator="red")
            return None

    def make_request(self, endpoint, method="GET", params=None):
        """Make API request to e-Boekhouden"""
        try:
            # Get session token first
            session_token = self.get_session_token()
            if not session_token:
                return {"success": False, "error": "Failed to get session token"}

            headers = {
                "Authorization": session_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            url = f"{self.base_url}/{endpoint}"

            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=120)
            else:
                response = requests.post(url, headers=headers, json=params, timeout=120)

            if response.status_code == 200:
                return {"success": True, "data": response.text, "status_code": response.status_code}
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:500]}",
                    "status_code": response.status_code,
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timeout - API call took too long"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_chart_of_accounts(self):
        """Get Chart of Accounts (Ledgers) - fetches ALL accounts with pagination"""
        try:
            all_accounts = []
            offset = 0
            limit = 500  # Use 500 per page for efficiency

            while True:
                # Get page of accounts
                result = self.make_request("v1/ledger", "GET", {"limit": limit, "offset": offset})

                if not result["success"]:
                    return result

                data = json.loads(result["data"])
                accounts = data.get("items", [])

                # Add accounts to collection
                all_accounts.extend(accounts)

                # Check if we got less than requested (end of data)
                if len(accounts) < limit:
                    break

                # Move to next page
                offset += limit

                # Safety check to prevent infinite loops
                if offset > 10000:
                    frappe.log_error("Safety limit reached in get_chart_of_accounts pagination")
                    break

            # Return complete data in same format as before
            return {"success": True, "data": json.dumps({"items": all_accounts}), "status_code": 200}

        except Exception as e:
            frappe.log_error(f"Error in get_chart_of_accounts: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_cost_centers(self):
        """Get Cost Centers - fetches ALL cost centers with pagination"""
        try:
            all_items = []
            offset = 0
            limit = 500

            while True:
                result = self.make_request("v1/costcenter", "GET", {"limit": limit, "offset": offset})

                if not result["success"]:
                    return result

                data = json.loads(result["data"])
                items = data.get("items", [])
                all_items.extend(items)

                if len(items) < limit:
                    break

                offset += limit
                if offset > 10000:
                    frappe.log_error("Safety limit reached in get_cost_centers pagination")
                    break

            return {"success": True, "data": json.dumps({"items": all_items}), "status_code": 200}
        except Exception as e:
            frappe.log_error(f"Error in get_cost_centers: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_invoices(self, params=None):
        """Get Invoices - fetches ALL invoices with pagination"""
        try:
            all_items = []
            offset = 0
            limit = 500

            if not params:
                params = {}

            while True:
                params_with_pagination = params.copy()
                params_with_pagination.update({"limit": limit, "offset": offset})

                result = self.make_request("v1/invoice", "GET", params_with_pagination)

                if not result["success"]:
                    return result

                data = json.loads(result["data"])
                items = data.get("items", [])
                all_items.extend(items)

                if len(items) < limit:
                    break

                offset += limit
                if offset > 50000:  # Higher limit for invoices
                    frappe.log_error("Safety limit reached in get_invoices pagination")
                    break

            return {"success": True, "data": json.dumps({"items": all_items}), "status_code": 200}
        except Exception as e:
            frappe.log_error(f"Error in get_invoices: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_invoice_templates(self):
        """Get Invoice Templates"""
        return self.make_request("v1/invoicetemplate")

    def get_email_templates(self):
        """Get Email Templates"""
        return self.make_request("v1/emailtemplate")

    def get_administrations(self):
        """Get Administrations"""
        return self.make_request("v1/administration")

    def get_linked_administrations(self):
        """Get Linked Administrations"""
        return self.make_request("v1/administration/linked")

    def get_relations(self, params=None):
        """Get Relations (Customers/Suppliers) - fetches ALL relations with pagination"""
        try:
            all_items = []
            offset = 0
            limit = 500

            if not params:
                params = {}

            while True:
                params_with_pagination = params.copy()
                params_with_pagination.update({"limit": limit, "offset": offset})

                result = self.make_request("v1/relation", "GET", params_with_pagination)

                if not result["success"]:
                    return result

                data = json.loads(result["data"])
                items = data.get("items", [])
                all_items.extend(items)

                if len(items) < limit:
                    break

                offset += limit
                if offset > 10000:
                    frappe.log_error("Safety limit reached in get_relations pagination")
                    break

            return {"success": True, "data": json.dumps({"items": all_items}), "status_code": 200}
        except Exception as e:
            frappe.log_error(f"Error in get_relations: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_customers(self, params=None):
        """Get Customers (Relations with type filter)"""
        if not params:
            params = {}
        params["relationType"] = "Customer"
        return self.get_relations(params)

    def get_suppliers(self, params=None):
        """Get Suppliers (Relations with type filter)"""
        if not params:
            params = {}
        params["relationType"] = "Supplier"
        return self.get_relations(params)

    def get_mutations(self, params=None):
        """Get Mutations (Transactions) - fetches ALL mutations with pagination"""
        try:
            all_items = []
            offset = 0
            limit = 500

            if not params:
                params = {}

            while True:
                params_with_pagination = params.copy()
                params_with_pagination.update({"limit": limit, "offset": offset})

                result = self.make_request("v1/mutation", "GET", params_with_pagination)

                if not result["success"]:
                    return result

                data = json.loads(result["data"])
                items = data.get("items", [])
                all_items.extend(items)

                if len(items) < limit:
                    break

                offset += limit
                if offset > 50000:  # Higher limit for mutations
                    frappe.log_error("Safety limit reached in get_mutations pagination")
                    break

            return {"success": True, "data": json.dumps({"items": all_items}), "status_code": 200}
        except Exception as e:
            frappe.log_error(f"Error in get_mutations: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_documents(self, params=None):
        """Get Documents/Attachments"""
        return self.make_request("v1/document", params=params)

    def get_invoice_documents(self, invoice_id, params=None):
        """Get documents for a specific invoice"""
        return self.make_request("v1/invoice/{invoice_id}/document", params=params)

    def download_document(self, document_id):
        """Download a specific document"""
        return self.make_request("v1/document/{document_id}/download")

    def get_invoice_detail(self, invoice_id):
        """Get detailed invoice information including attachments"""
        return self.make_request("v1/invoice/{invoice_id}")


class EBoekhoudenXMLParser:
    """XML parser for e-Boekhouden API responses"""

    @staticmethod
    def parse_grootboekrekeningen(xml_data):
        """Parse Chart of Accounts XML"""
        try:
            accounts = []

            # Handle both direct XML and response wrapper
            if "<?xml" in xml_data:
                root = ET.fromstring(xml_data)
            else:
                # Wrap in root element if needed
                xml_data = f"<root>{xml_data}</root>"
                root = ET.fromstring(xml_data)

            # Find all Grootboekrekening elements
            for account_elem in root.findall(".//Grootboekrekening"):
                account = {}
                for child in account_elem:
                    account[child.tag] = child.text

                accounts.append(
                    {
                        "code": account.get("Code", ""),
                        "name": account.get("Omschrijving", ""),
                        "category": account.get("Categorie", ""),
                        "group": account.get("Groep", ""),
                        "eb_data": account,
                    }
                )

            return accounts

        except ET.ParseError as e:
            frappe.log_error(f"XML Parse Error in grootboekrekeningen: {str(e)}")
            return []
        except Exception as e:
            frappe.log_error(f"Error parsing grootboekrekeningen: {str(e)}")
            return []

    @staticmethod
    def parse_relaties(xml_data):
        """Parse Relations (Customers/Suppliers) XML"""
        try:
            relations = []

            if "<?xml" in xml_data:
                root = ET.fromstring(xml_data)
            else:
                xml_data = f"<root>{xml_data}</root>"
                root = ET.fromstring(xml_data)

            for relation_elem in root.findall(".//Relatie"):
                relation = {}
                for child in relation_elem:
                    relation[child.tag] = child.text

                relations.append(
                    {
                        "code": relation.get("Code", ""),
                        "company_name": relation.get("Bedrij", ""),
                        "contact_name": relation.get("Contactpersoon", ""),
                        "address": relation.get("Adres", ""),
                        "postcode": relation.get("Postcode", ""),
                        "city": relation.get("Plaats", ""),
                        "country": relation.get("Land", ""),
                        "phone": relation.get("Telefoon", ""),
                        "email": relation.get("Email", ""),
                        "website": relation.get("Website", ""),
                        "vat_number": relation.get("BtwNummer", ""),
                        "eb_data": relation,
                    }
                )

            return relations

        except ET.ParseError as e:
            frappe.log_error(f"XML Parse Error in relaties: {str(e)}")
            return []
        except Exception as e:
            frappe.log_error(f"Error parsing relaties: {str(e)}")
            return []

    @staticmethod
    def parse_mutaties(xml_data):
        """Parse Transactions (Mutaties) XML"""
        try:
            transactions = []

            if "<?xml" in xml_data:
                root = ET.fromstring(xml_data)
            else:
                xml_data = f"<root>{xml_data}</root>"
                root = ET.fromstring(xml_data)

            for mutatie_elem in root.findall(".//Mutatie"):
                mutatie = {}
                for child in mutatie_elem:
                    mutatie[child.tag] = child.text

                transactions.append(
                    {
                        "number": mutatie.get("MutatieNr", ""),
                        "date": mutatie.get("Datum", ""),
                        "account_code": mutatie.get("Rekening", ""),
                        "account_name": mutatie.get("RekeningOmschrijving", ""),
                        "description": mutatie.get("Omschrijving", ""),
                        "debit": float(mutatie.get("Debet", 0) or 0),
                        "credit": float(mutatie.get("Credit", 0) or 0),
                        "invoice_number": mutatie.get("Factuurnummer", ""),
                        "relation_code": mutatie.get("RelatieCode", ""),
                        "eb_data": mutatie,
                    }
                )

            return transactions

        except ET.ParseError as e:
            frappe.log_error(f"XML Parse Error in mutaties: {str(e)}")
            return []
        except Exception as e:
            frappe.log_error(f"Error parsing mutaties: {str(e)}")
            return []


@frappe.whitelist()
def update_api_url():
    """Update API URL to the correct modern endpoint"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        settings.api_url = "https://api.e-boekhouden.nl"
        settings.source_application = "ERPNext"  # Standard source format
        settings.save()

        return {
            "success": True,
            "message": "API URL and source updated",
            "new_url": settings.api_url,
            "new_source": settings.source_application,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_api_connection():
    """Test API connection and return sample data"""
    try:
        api = EBoekhoudenAPI()

        # Test with Chart of Accounts using correct endpoint
        result = api.get_chart_of_accounts()

        if result["success"]:
            return {
                "success": True,
                "message": "API connection successful",
                "sample_data": result["data"][:500] + "..." if len(result["data"]) > 500 else result["data"],
            }
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        frappe.log_error(f"Error testing API connection: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def preview_chart_of_accounts():
    """Preview Chart of Accounts data"""
    try:
        api = EBoekhoudenAPI()
        result = api.get_chart_of_accounts()

        if result["success"]:
            # Parse JSON response instead of XML
            try:
                data = json.loads(result["data"])
                accounts = data.get("items", [])

                # Convert to simplified format
                simplified_accounts = []
                for account in accounts[:10]:  # First 10 for preview
                    simplified_accounts.append(
                        {
                            "id": account.get("id"),
                            "code": account.get("code"),
                            "description": account.get("description"),
                            "category": account.get("category"),
                            "group": account.get("group", ""),
                        }
                    )

                return {
                    "success": True,
                    "message": f"Found {len(accounts)} accounts",
                    "accounts": simplified_accounts,
                    "total_count": len(accounts),
                }
            except json.JSONDecodeError as e:
                return {"success": False, "error": f"Failed to parse API response: {str(e)}"}
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        frappe.log_error(f"Error previewing Chart of Accounts: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def preview_customers():
    """Preview Customers data"""
    try:
        api = EBoekhoudenAPI()
        result = api.get_customers()

        if result["success"]:
            # Parse JSON response instead of XML
            try:
                data = json.loads(result["data"])
                customers = data.get("items", [])

                # Convert to simplified format
                simplified_customers = []
                for customer in customers[:10]:  # First 10 for preview
                    simplified_customers.append(
                        {
                            "id": customer.get("id"),
                            "name": customer.get("name", ""),
                            "companyName": customer.get("companyName", ""),
                            "contactName": customer.get("contactName", ""),
                            "email": customer.get("email", ""),
                            "city": customer.get("city", ""),
                        }
                    )

                return {
                    "success": True,
                    "message": "Found {len(customers)} customers",
                    "customers": simplified_customers,
                    "total_count": len(customers),
                }
            except json.JSONDecodeError as e:
                return {"success": False, "error": f"Failed to parse API response: {str(e)}"}
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        frappe.log_error(f"Error previewing Customers: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def preview_suppliers():
    """Preview Suppliers data"""
    try:
        api = EBoekhoudenAPI()
        result = api.get_suppliers()

        if result["success"]:
            # Parse JSON response
            try:
                data = json.loads(result["data"])
                suppliers = data.get("items", [])

                # Convert to simplified format
                simplified_suppliers = []
                for supplier in suppliers[:10]:  # First 10 for preview
                    simplified_suppliers.append(
                        {
                            "id": supplier.get("id"),
                            "name": supplier.get("name", ""),
                            "companyName": supplier.get("companyName", ""),
                            "contactName": supplier.get("contactName", ""),
                            "email": supplier.get("email", ""),
                            "city": supplier.get("city", ""),
                            "vatNumber": supplier.get("vatNumber", ""),
                        }
                    )

                return {
                    "success": True,
                    "message": "Found {len(suppliers)} suppliers",
                    "suppliers": simplified_suppliers,
                    "total_count": len(suppliers),
                }
            except json.JSONDecodeError as e:
                return {"success": False, "error": f"Failed to parse API response: {str(e)}"}
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        frappe.log_error(f"Error previewing Suppliers: {str(e)}")
        return {"success": False, "error": str(e)}


def update_dashboard_data_periodically():
    """Scheduled task to update dashboard data"""
    try:
        # Check if dashboard exists
        if frappe.db.exists("E-Boekhouden Dashboard", "E-Boekhouden Dashboard"):
            dashboard = frappe.get_single("E-Boekhouden Dashboard")
            dashboard.load_dashboard_data()
            frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error in periodic dashboard update: {str(e)}", "E-Boekhouden Dashboard")


@frappe.whitelist()
def get_dashboard_data_api():
    """API endpoint for dashboard data (properly whitelisted)"""
    return test_dashboard_data()


@frappe.whitelist()
def fix_account_types():
    """Fix migrated accounts that have party requirements"""
    try:
        # Find migrated accounts that are Receivable/Payable
        receivable_accounts = frappe.db.get_all(
            "Account",
            {"account_type": "Receivable", "account_number": ["!=", ""]},
            ["name", "account_name", "account_number"],
        )

        payable_accounts = frappe.db.get_all(
            "Account",
            {"account_type": "Payable", "account_number": ["!=", ""]},
            ["name", "account_name", "account_number"],
        )

        fixed_accounts = []

        # Fix Receivable accounts
        for account in receivable_accounts:
            frappe.db.set_value("Account", account.name, "account_type", "Current Asset")
            fixed_accounts.append("{account.name} (Receivable → Current Asset)")

        # Fix Payable accounts
        for account in payable_accounts:
            frappe.db.set_value("Account", account.name, "account_type", "Current Liability")
            fixed_accounts.append("{account.name} (Payable → Current Liability)")

        frappe.db.commit()

        return {
            "success": True,
            "message": "Fixed {len(fixed_accounts)} accounts",
            "fixed_accounts": fixed_accounts,
        }

    except Exception as e:
        frappe.log_error(f"Error fixing account types: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def explore_invoice_fields():
    """Explore what fields are available in invoice data"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        results = {}

        # Try different parameters to get invoice data
        test_params = [
            {"limit": 10},
            {"limit": 50},
            {"dateFrom": "2023-01-01", "dateTo": "2024-12-31", "limit": 20},
            {"dateFrom": "2022-01-01", "dateTo": "2024-12-31", "limit": 20},
            {},  # No params
        ]

        for i, params in enumerate(test_params):
            result = api.get_invoices(params)

            if result["success"]:
                import json

                data = json.loads(result["data"])
                results["test_{i}"] = {
                    "params": params,
                    "success": True,
                    "items_count": len(data.get("items", [])),
                    "raw_sample": result["data"][:500] if len(result["data"]) > 500 else result["data"],
                }

                # If we found items, analyze the first one in detail
                if data.get("items"):
                    first_item = data["items"][0]
                    results["test_{i}"]["first_item_analysis"] = {
                        "all_keys": list(first_item.keys()),
                        "file_related_keys": [
                            k
                            for k in first_item.keys()
                            if any(
                                word in k.lower()
                                for word in [
                                    "file",
                                    "document",
                                    "attachment",
                                    "pdf",
                                    "image",
                                    "link",
                                    "url",
                                    "path",
                                ]
                            )
                        ],
                        "full_first_item": first_item,
                    }
                    # Stop after finding the first successful result with data
                    break
            else:
                results["test_{i}"] = {
                    "params": params,
                    "success": False,
                    "error": result.get("error"),
                    "status_code": result.get("status_code"),
                }

        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_equity_import_status():
    """Check if equity mutations are actually being imported correctly"""
    try:
        # Check if these specific mutations were imported
        equity_mutations = [6738, 6352, 4595, 3698]
        results = {"success": True, "mutations_checked": len(equity_mutations), "import_status": []}

        for mutation_id in equity_mutations:
            # Check if Journal Entry exists for this mutation
            existing_je = frappe.db.get_value(
                "Journal Entry",
                {"eboekhouden_mutation_nr": str(mutation_id)},
                ["name", "posting_date", "title", "total_debit", "total_credit"],
            )

            status = {
                "mutation_id": mutation_id,
                "imported": bool(existing_je),
            }

            if existing_je:
                status.update(
                    {
                        "document_name": existing_je[0],
                        "posting_date": existing_je[1],
                        "title": existing_je[2],
                        "total_debit": existing_je[3],
                        "total_credit": existing_je[4],
                    }
                )

                # Get the actual journal entry lines
                je_accounts = frappe.db.get_all(
                    "Journal Entry Account",
                    filters={"parent": existing_je[0]},
                    fields=[
                        "account",
                        "debit_in_account_currency",
                        "credit_in_account_currency",
                        "user_remark",
                    ],
                )
                status["journal_lines"] = je_accounts
            else:
                status["reason_not_imported"] = "Not found in Journal Entry table"

                # Check if it was skipped or failed
                # Look for it in error logs or cache
                cached_mutation = frappe.db.get_value(
                    "EBoekhouden REST Mutation Cache",
                    {"mutation_id": str(mutation_id)},
                    ["name", "mutation_type", "mutation_date"],
                )

                if cached_mutation:
                    status["cached"] = True
                    status["cache_info"] = {
                        "name": cached_mutation[0],
                        "type": cached_mutation[1],
                        "date": cached_mutation[2],
                    }
                else:
                    status["cached"] = False

            results["import_status"].append(status)

        return results

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_mutation_type_name_for_analysis(mutation_type):
    """Get human-readable name for mutation type"""
    type_mapping = {
        0: "Openstaande post (Opening Balance)",
        1: "Factuurontvangst (Purchase Invoice)",
        2: "Factuurbetaling (Sales Invoice)",
        3: "FactuurbetalingOntvangen (Customer Payment)",
        4: "FactuurbetalingVerstuurd (Supplier Payment)",
        5: "GeldOntvangen (Money Received)",
        6: "GeldUitgegeven (Money Spent)",
        7: "Memoriaal (Memorial/Journal)",
    }
    return type_mapping.get(mutation_type, f"Unknown Type {mutation_type}")


def get_ledger_info_for_analysis(ledger_id):
    """Get ledger mapping information"""
    try:
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": str(ledger_id)},
            ["erpnext_account", "ledger_code", "ledger_description"],
            as_dict=True,
        )

        if mapping and mapping.get("erpnext_account"):
            account_info = frappe.db.get_value(
                "Account", mapping["erpnext_account"], ["account_name", "account_type"], as_dict=True
            )
            if account_info:
                mapping.update(account_info)

        return mapping
    except frappe.DoesNotExistError:
        frappe.log_error(
            message=f"Ledger mapping not found for ledger ID: {ledger_id}",
            title="E-Boekhouden - Ledger Mapping Not Found",
            reference_doctype="E-Boekhouden Ledger Mapping",
            reference_name=str(ledger_id),
        )
        return None
    except Exception as e:
        frappe.log_error(
            message=f"Failed to retrieve ledger info for ledger ID {ledger_id}: {str(e)}",
            title="E-Boekhouden - Ledger Info Retrieval Failed",
            reference_doctype="E-Boekhouden Ledger Mapping",
            reference_name=str(ledger_id),
        )
        return None


@frappe.whitelist()
def compare_api_relation_data():
    """Compare SOAP vs REST API for relation data quality"""
    results = {
        "rest_api": {"status": "unknown", "relations": [], "error": None},
        "soap_api": {"status": "unknown", "relations": [], "error": None},
    }

    # Test REST API
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        rest_api = EBoekhoudenAPI(settings)

        # Get a sample of customers
        rest_result = rest_api.get_customers({"limit": 10})
        if rest_result["success"]:
            data = json.loads(rest_result["data"])
            customers = data.get("items", [])

            results["rest_api"]["status"] = "success"
            results["rest_api"]["total_count"] = len(customers)
            results["rest_api"]["relations"] = customers[:3]  # First 3 for comparison

            # Analyze data quality
            meaningful_names = 0
            for customer in customers:
                name = customer.get("name", "").strip()
                company = customer.get("companyName", "").strip()
                contact = customer.get("contactName", "").strip()
                if name or company or contact:
                    meaningful_names += 1

            results["rest_api"]["meaningful_names"] = meaningful_names
            results["rest_api"]["meaningful_percentage"] = (
                (meaningful_names / len(customers) * 100) if customers else 0
            )
        else:
            results["rest_api"]["status"] = "failed"
            results["rest_api"]["error"] = rest_result.get("error")

    except Exception as e:
        results["rest_api"]["status"] = "error"
        results["rest_api"]["error"] = str(e)

    # Test SOAP API
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_soap_api import EBoekhoudenSOAPAPI

        soap_api = EBoekhoudenSOAPAPI(settings)

        # Try to get relations via SOAP
        soap_result = soap_api.get_relaties()
        if soap_result["success"]:
            relations = soap_result.get("relations", [])

            results["soap_api"]["status"] = "success"
            results["soap_api"]["total_count"] = len(relations)
            results["soap_api"]["relations"] = relations[:3]  # First 3 for comparison

            # Analyze data quality - SOAP uses different field names
            meaningful_names = 0
            for relation in relations:
                # Common SOAP fields: Bedrijf, Contactpersoon, etc.
                company = relation.get("Bedrijf", "").strip()
                contact = relation.get("Contactpersoon", "").strip()
                name = relation.get("Naam", "").strip()
                if name or company or contact:
                    meaningful_names += 1

            results["soap_api"]["meaningful_names"] = meaningful_names
            results["soap_api"]["meaningful_percentage"] = (
                (meaningful_names / len(relations) * 100) if relations else 0
            )
        else:
            results["soap_api"]["status"] = "failed"
            results["soap_api"]["error"] = soap_result.get("error")

    except Exception as e:
        results["soap_api"]["status"] = "error"
        results["soap_api"]["error"] = str(e)

    # Generate comparison summary
    summary = {
        "rest_api_working": results["rest_api"]["status"] == "success",
        "soap_api_working": results["soap_api"]["status"] == "success",
        "recommendation": "Unknown",
    }

    if results["rest_api"]["status"] == "success" and results["soap_api"]["status"] == "success":
        rest_percentage = results["rest_api"]["meaningful_percentage"]
        soap_percentage = results["soap_api"]["meaningful_percentage"]

        if soap_percentage > rest_percentage + 10:  # 10% threshold
            summary["recommendation"] = "SOAP API has significantly better data quality"
        elif rest_percentage > soap_percentage + 10:
            summary["recommendation"] = "REST API has significantly better data quality"
        else:
            summary[
                "recommendation"
            ] = "Both APIs have similar data quality, prefer REST API (not deprecated)"
    elif results["soap_api"]["status"] == "success":
        summary["recommendation"] = "Only SOAP API works, but it's deprecated"
    elif results["rest_api"]["status"] == "success":
        summary["recommendation"] = "Only REST API works (preferred)"
    else:
        summary["recommendation"] = "Neither API is working properly"

    results["summary"] = summary
    return results
