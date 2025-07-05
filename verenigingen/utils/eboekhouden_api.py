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
        self.base_url = settings.api_url.rstrip("/")  # Remove trailing slash
        self.api_token = settings.get_password("api_token")
        self.source = settings.source_application or "Verenigingen ERPNext"

    def get_session_token(self):
        """Get session token using API token"""
        try:
            session_url = f"{self.base_url}/v1/session"
            session_data = {"accessToken": self.api_token, "source": self.source}

            response = requests.post(session_url, json=session_data, timeout=30)

            if response.status_code == 200:
                session_response = response.json()
                return session_response.get("token")
            else:
                frappe.log_error(f"Session token request failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            frappe.log_error(f"Error getting session token: {str(e)}")
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
        return self.make_request(f"v1/invoice/{invoice_id}/document", params=params)

    def download_document(self, document_id):
        """Download a specific document"""
        return self.make_request(f"v1/document/{document_id}/download")

    def get_invoice_detail(self, invoice_id):
        """Get detailed invoice information including attachments"""
        return self.make_request(f"v1/invoice/{invoice_id}")


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
def debug_settings():
    """Debug E-Boekhouden Settings"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        # Check basic fields
        result = {
            "settings_exists": True,
            "api_url": settings.api_url,
            "source_application": settings.source_application,
            "api_token_field_populated": bool(settings.get("api_token")),
        }

        # Try to get the password
        try:
            token = settings.get_password("api_token")
            result["api_token_password_accessible"] = bool(token)
            if token:
                result["token_length"] = len(token)
        except Exception as e:
            result["password_error"] = str(e)

        # Check raw database value
        raw_token = frappe.db.get_value("E-Boekhouden Settings", "E-Boekhouden Settings", "api_token")
        result["raw_token_exists"] = bool(raw_token)

        return result

    except Exception as e:
        return {"error": str(e), "settings_exists": False}


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
def test_session_token_only():
    """Test just the session token creation with detailed logging"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        session_url = f"{settings.api_url}/v1/session"
        session_data = {
            "accessToken": settings.get_password("api_token"),
            "source": settings.source_application or "ERPNext",
        }

        frappe.log_error(f"Testing session token with URL: {session_url}")
        frappe.log_error(f"Session data: {{'accessToken': '***', 'source': '{session_data['source']}'}}")

        response = requests.post(session_url, json=session_data, timeout=30)

        result = {
            "url": session_url,
            "source": session_data["source"],
            "status_code": response.status_code,
            "response_text": response.text[:1000],  # First 1000 chars
            "headers": dict(response.headers),
        }

        if response.status_code == 200:
            try:
                json_response = response.json()
                result["session_token_received"] = bool(json_response.get("sessionToken"))
                result["success"] = True
            except Exception:
                result["json_parse_error"] = True
                result["success"] = False
        else:
            result["success"] = False

        return result

    except Exception as e:
        return {"success": False, "error": str(e), "exception_type": type(e).__name__}


@frappe.whitelist()
def discover_api_structure():
    """Try to discover the API structure by testing various approaches"""
    try:
        api = EBoekhoudenAPI()

        # Test basic endpoints and root paths
        discovery_tests = [
            ("", "Root"),
            ("v1", "Version 1 root"),
            ("api", "API root"),
            ("api/v1", "API v1 root"),
            ("swagger.json", "Swagger spec"),
            ("swagger/v1/swagger.json", "Swagger v1 spec"),
            ("docs", "Documentation"),
            ("health", "Health check"),
            ("status", "Status check"),
        ]

        results = {}

        for endpoint, description in discovery_tests:
            result = api.make_request(endpoint)
            results[endpoint] = {
                "description": description,
                "success": result["success"],
                "status_code": result.get("status_code"),
                "error": result.get("error"),
                "response_preview": result.get("data", "")[:500] if result["success"] else None,
            }

        return {"success": True, "message": "API discovery completed", "results": results}

    except Exception as e:
        frappe.log_error(f"Error discovering API structure: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_raw_request():
    """Test a raw HTTP request to understand the API better"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        # Get session token
        session_url = f"{settings.api_url}/v1/session"
        session_data = {
            "accessToken": settings.get_password("api_token"),
            "source": settings.source_application or "ERPNext",
        }

        session_response = requests.post(session_url, json=session_data, timeout=30)

        if session_response.status_code != 200:
            return {
                "success": False,
                "error": f"Session token failed: {session_response.status_code} - {session_response.text}",
            }

        token = session_response.json().get("token")

        # Try a simple GET to the base API URL with the token
        headers = {"Authorization": token, "Accept": "application/json"}

        # Test different base URLs
        test_urls = [
            f"{settings.api_url}/",
            f"{settings.api_url}/v1/",
            f"{settings.api_url}/api/",
            f"{settings.api_url}/swagger.json",
        ]

        results = {}

        for test_url in test_urls:
            try:
                response = requests.get(test_url, headers=headers, timeout=15)
                results[test_url] = {
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "content_length": len(response.text),
                    "response_preview": response.text[:500],
                    "success": response.status_code == 200,
                }
            except Exception as e:
                results[test_url] = {"error": str(e), "success": False}

        return {"success": True, "token_obtained": bool(token), "test_results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_correct_endpoints():
    """Test the correct API endpoints from Swagger documentation"""
    try:
        api = EBoekhoudenAPI()

        # Test all available endpoints
        endpoint_tests = [
            ("v1/administration", "Administrations"),
            ("v1/ledger", "Chart of Accounts"),
            ("v1/costcenter", "Cost Centers"),
            ("v1/invoice", "Invoices"),
            ("v1/invoicetemplate", "Invoice Templates"),
            ("v1/emailtemplate", "Email Templates"),
        ]

        results = {}

        for endpoint, description in endpoint_tests:
            result = api.make_request(endpoint)
            results[endpoint] = {
                "description": description,
                "success": result["success"],
                "status_code": result.get("status_code"),
                "error": result.get("error"),
                "data_preview": result.get("data", "")[:300] if result["success"] else None,
            }

        return {
            "success": True,
            "message": "Endpoint testing completed with correct endpoints",
            "results": results,
        }

    except Exception as e:
        frappe.log_error(f"Error testing correct endpoints: {str(e)}")
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
def test_chart_of_accounts_migration():
    """Test Chart of Accounts migration in dry-run mode"""
    try:
        # Create a temporary migration document for testing
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"Test Migration {frappe.utils.now()}"
        migration.migrate_accounts = 1
        migration.migrate_cost_centers = 0
        migration.migrate_customers = 0
        migration.migrate_suppliers = 0
        migration.migrate_transactions = 0
        migration.dry_run = 1

        # Initialize counters
        migration.total_records = 0
        migration.imported_records = 0
        migration.failed_records = 0

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Run migration test
        result = migration.migrate_chart_of_accounts(settings)

        return {
            "success": True,
            "message": "Chart of Accounts migration test completed",
            "result": result,
            "imported_records": getattr(migration, "imported_records", 0),
            "failed_records": getattr(migration, "failed_records", 0),
            "total_records": getattr(migration, "total_records", 0),
        }

    except Exception as e:
        frappe.log_error(f"Error testing Chart of Accounts migration: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_cost_center_migration():
    """Test Cost Center migration in dry-run mode"""
    try:
        # Create a temporary migration document for testing
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"Test Cost Center Migration {frappe.utils.now()}"
        migration.migrate_accounts = 0
        migration.migrate_cost_centers = 1
        migration.migrate_customers = 0
        migration.migrate_suppliers = 0
        migration.migrate_transactions = 0
        migration.dry_run = 1

        # Initialize counters
        migration.total_records = 0
        migration.imported_records = 0
        migration.failed_records = 0

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Run migration test
        result = migration.migrate_cost_centers(settings)

        return {
            "success": True,
            "message": "Cost Center migration test completed",
            "result": result,
            "imported_records": getattr(migration, "imported_records", 0),
            "failed_records": getattr(migration, "failed_records", 0),
            "total_records": getattr(migration, "total_records", 0),
        }

    except Exception as e:
        frappe.log_error(f"Error testing Cost Center migration: {str(e)}")
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
                    "message": f"Found {len(customers)} customers",
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
                    "message": f"Found {len(suppliers)} suppliers",
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


@frappe.whitelist()
def test_customer_migration():
    """Test Customer migration in dry-run mode"""
    try:
        # Create a temporary migration document for testing
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"Test Customer Migration {frappe.utils.now()}"
        migration.migrate_accounts = 0
        migration.migrate_cost_centers = 0
        migration.migrate_customers = 1
        migration.migrate_suppliers = 0
        migration.migrate_transactions = 0
        migration.dry_run = 1

        # Initialize counters
        migration.total_records = 0
        migration.imported_records = 0
        migration.failed_records = 0

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Run migration test
        result = migration.migrate_customers(settings)

        return {
            "success": True,
            "message": "Customer migration test completed",
            "result": result,
            "imported_records": getattr(migration, "imported_records", 0),
            "failed_records": getattr(migration, "failed_records", 0),
            "total_records": getattr(migration, "total_records", 0),
        }

    except Exception as e:
        frappe.log_error(f"Error testing Customer migration: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_supplier_migration():
    """Test Supplier migration in dry-run mode"""
    try:
        # Create a temporary migration document for testing
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"Test Supplier Migration {frappe.utils.now()}"
        migration.migrate_accounts = 0
        migration.migrate_cost_centers = 0
        migration.migrate_customers = 0
        migration.migrate_suppliers = 1
        migration.migrate_transactions = 0
        migration.dry_run = 1

        # Initialize counters
        migration.total_records = 0
        migration.imported_records = 0
        migration.failed_records = 0

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Run migration test
        result = migration.migrate_suppliers(settings)

        return {
            "success": True,
            "message": "Supplier migration test completed",
            "result": result,
            "imported_records": getattr(migration, "imported_records", 0),
            "failed_records": getattr(migration, "failed_records", 0),
            "total_records": getattr(migration, "total_records", 0),
        }

    except Exception as e:
        frappe.log_error(f"Error testing Supplier migration: {str(e)}")
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
def test_simple_migration():
    """Simple test to isolate migration issue"""
    try:
        # Create a very basic migration document
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = "Simple Test"
        migration.migrate_accounts = 0
        migration.migrate_cost_centers = 0
        migration.migrate_customers = 1
        migration.migrate_suppliers = 0
        migration.migrate_transactions = 0
        migration.dry_run = 1

        return {"success": True, "message": "Simple migration document created successfully"}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def create_test_migration():
    """Create a test migration record for dashboard testing"""
    try:
        companies = frappe.get_all("Company", limit=1)
        if not companies:
            return {"success": False, "error": "No company found"}

        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = "Dashboard Test Migration"
        migration.company = companies[0].name
        migration.migrate_accounts = 1
        migration.dry_run = 1
        migration.migration_status = "Completed"
        migration.total_records = 100
        migration.imported_records = 95
        migration.failed_records = 5
        migration.insert()

        return {
            "success": True,
            "message": f"Created test migration: {migration.name}",
            "migration_name": migration.name,
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def get_dashboard_data_api():
    """API endpoint for dashboard data (properly whitelisted)"""
    return test_dashboard_data()


@frappe.whitelist()
def test_dashboard_data():
    """Test dashboard data collection without creating dashboard doc"""
    try:
        # Test migration statistics
        migration_stats = {
            "total": frappe.db.count("E-Boekhouden Migration"),
            "completed": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Completed"}),
            "in_progress": frappe.db.count("E-Boekhouden Migration", {"migration_status": "In Progress"}),
            "failed": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Failed"}),
            "draft": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Draft"}),
        }

        # Test API connection
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)
        connection_test = api.get_chart_of_accounts()
        connection_status = "Connected" if connection_test["success"] else "Disconnected"

        # Test available data counts
        available_data = {"accounts": 0, "cost_centers": 0, "customers": 0, "suppliers": 0}

        if connection_test["success"]:
            # Chart of Accounts
            result = api.get_chart_of_accounts()
            if result["success"]:
                import json

                data = json.loads(result["data"])
                available_data["accounts"] = len(data.get("items", []))

            # Cost Centers
            result = api.get_cost_centers()
            if result["success"]:
                data = json.loads(result["data"])
                available_data["cost_centers"] = len(data.get("items", []))

            # Customers
            result = api.get_customers()
            if result["success"]:
                data = json.loads(result["data"])
                available_data["customers"] = len(data.get("items", []))

            # Suppliers
            result = api.get_suppliers()
            if result["success"]:
                data = json.loads(result["data"])
                available_data["suppliers"] = len(data.get("items", []))

        return {
            "success": True,
            "migration_stats": migration_stats,
            "connection_status": connection_status,
            "available_data": available_data,
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def debug_transaction_data():
    """Debug transaction data from e-Boekhouden"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Get a sample of transactions
        from datetime import datetime, timedelta

        today = datetime.now()
        last_month = today - timedelta(days=30)

        params = {"dateFrom": last_month.strftime("%Y-%m-%d"), "dateTo": today.strftime("%Y-%m-%d")}

        result = api.get_mutations(params)

        if result["success"]:
            data = json.loads(result["data"])
            transactions = data.get("items", [])

            # Analyze the first few transactions
            sample_analysis = []
            for i, trans in enumerate(transactions[:5]):
                analysis = {
                    "index": i,
                    "raw_data": trans,
                    "date": trans.get("date"),
                    "description": trans.get("description"),
                    "debit": trans.get("debit"),
                    "credit": trans.get("credit"),
                    "account_code": trans.get("accountCode"),
                    "has_date": bool(trans.get("date")),
                    "has_description": bool(trans.get("description")),
                    "has_amount": bool(trans.get("debit") or trans.get("credit")),
                }
                sample_analysis.append(analysis)

            return {
                "success": True,
                "total_transactions": len(transactions),
                "sample_analysis": sample_analysis,
            }
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        frappe.log_error(f"Error debugging transaction data: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_ledger_id_mapping():
    """Test the mapping between ledger IDs and account codes"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Get chart of accounts
        accounts_result = api.get_chart_of_accounts()
        if not accounts_result["success"]:
            return {"success": False, "error": "Failed to get chart of accounts"}

        accounts_data = json.loads(accounts_result["data"])
        accounts = accounts_data.get("items", [])

        # Get sample transactions
        from datetime import datetime, timedelta

        today = datetime.now()
        last_month = today - timedelta(days=30)

        params = {"dateFrom": last_month.strftime("%Y-%m-%d"), "dateTo": today.strftime("%Y-%m-%d")}

        transactions_result = api.get_mutations(params)
        if not transactions_result["success"]:
            return {"success": False, "error": "Failed to get transactions"}

        transactions_data = json.loads(transactions_result["data"])
        transactions = transactions_data.get("items", [])

        # Build ledger ID to account code mapping
        ledger_mapping = {}
        for account in accounts:
            account_id = account.get("id")
            account_code = account.get("code")
            if account_id and account_code:
                ledger_mapping[str(account_id)] = account_code

        # Analyze first few transactions
        analysis = {
            "total_accounts": len(accounts),
            "total_transactions": len(transactions),
            "ledger_mapping_sample": dict(list(ledger_mapping.items())[:5]),
            "transaction_analysis": [],
        }

        for i, trans in enumerate(transactions[:5]):
            ledger_id = str(trans.get("ledgerId", ""))
            account_code = ledger_mapping.get(ledger_id)

            trans_analysis = {
                "transaction": trans,
                "ledger_id": ledger_id,
                "mapped_account_code": account_code,
                "mapping_found": bool(account_code),
            }
            analysis["transaction_analysis"].append(trans_analysis)

        return {"success": True, "analysis": analysis}

    except Exception as e:
        frappe.log_error(f"Error testing ledger ID mapping: {str(e)}")
        return {"success": False, "error": str(e)}


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
            fixed_accounts.append(f"{account.name} (Receivable → Current Asset)")

        # Fix Payable accounts
        for account in payable_accounts:
            frappe.db.set_value("Account", account.name, "account_type", "Current Liability")
            fixed_accounts.append(f"{account.name} (Payable → Current Liability)")

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Fixed {len(fixed_accounts)} accounts",
            "fixed_accounts": fixed_accounts,
        }

    except Exception as e:
        frappe.log_error(f"Error fixing account types: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_document_retrieval():
    """Test e-Boekhouden document/attachment retrieval capabilities"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        results = {"document_endpoints": {}, "invoice_sample": None, "document_sample": None}

        # Test general documents endpoint
        try:
            doc_result = api.get_documents()
            results["document_endpoints"]["v1/document"] = {
                "success": doc_result["success"],
                "status_code": doc_result.get("status_code"),
                "data_sample": doc_result["data"][:500]
                if doc_result["success"]
                else doc_result.get("error", ""),
            }
        except Exception as e:
            results["document_endpoints"]["v1/document"] = {"error": str(e)}

        # Get some invoices first to test document retrieval
        try:
            invoices_result = api.get_invoices({"limit": 5})
            if invoices_result["success"]:
                import json

                invoices_data = json.loads(invoices_result["data"])
                if "items" in invoices_data and invoices_data["items"]:
                    first_invoice = invoices_data["items"][0]
                    results["invoice_sample"] = {
                        "id": first_invoice.get("id"),
                        "number": first_invoice.get("number", first_invoice.get("invoiceNumber")),
                        "keys": list(first_invoice.keys()),
                    }

                    # Test invoice-specific document retrieval
                    if "id" in first_invoice:
                        try:
                            invoice_docs = api.get_invoice_documents(first_invoice["id"])
                            results["document_endpoints"]["v1/invoice/{id}/document"] = {
                                "success": invoice_docs["success"],
                                "status_code": invoice_docs.get("status_code"),
                                "data_sample": invoice_docs["data"][:500]
                                if invoice_docs["success"]
                                else invoice_docs.get("error", ""),
                            }
                        except Exception as e:
                            results["document_endpoints"]["v1/invoice/{id}/document"] = {"error": str(e)}

                        # Test detailed invoice info
                        try:
                            invoice_detail = api.get_invoice_detail(first_invoice["id"])
                            results["document_endpoints"]["v1/invoice/{id}"] = {
                                "success": invoice_detail["success"],
                                "status_code": invoice_detail.get("status_code"),
                                "data_sample": invoice_detail["data"][:500]
                                if invoice_detail["success"]
                                else invoice_detail.get("error", ""),
                            }
                        except Exception as e:
                            results["document_endpoints"]["v1/invoice/{id}"] = {"error": str(e)}

        except Exception as e:
            results["invoice_sample"] = {"error": str(e)}

        # Test if there are any endpoints with 'attachment', 'file', 'pdf' in the response
        test_endpoints = ["v1/attachment", "v1/file", "v1/pd", "v1/upload", "v1/download"]

        for endpoint in test_endpoints:
            try:
                test_result = api.make_request(endpoint)
                results["document_endpoints"][endpoint] = {
                    "success": test_result["success"],
                    "status_code": test_result.get("status_code"),
                    "data_sample": test_result["data"][:200]
                    if test_result["success"]
                    else test_result.get("error", "")[:200],
                }
            except Exception as e:
                results["document_endpoints"][endpoint] = {"error": str(e)}

        return {
            "success": True,
            "results": results,
            "summary": f"Tested {len(results['document_endpoints'])} document-related endpoints",
        }

    except Exception as e:
        frappe.log_error(f"Error testing document retrieval: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_token_issue_debug():
    """Test token issue with detailed logging"""
    try:
        # Test the settings
        settings = frappe.get_single("E-Boekhouden Settings")

        result = {
            "api_url": settings.api_url,
            "source": settings.source_application,
        }

        # Test token retrieval
        token = settings.get_password("api_token")
        result["token_available"] = bool(token)
        result["token_length"] = len(token) if token else 0

        # Test API class initialization
        api = EBoekhoudenAPI(settings)
        result["api_initialized"] = True

        # Test session token
        session_token = api.get_session_token()
        result["session_token_obtained"] = bool(session_token)

        if session_token:
            result["session_token_length"] = len(session_token)

            # Test a simple API call
            api_result = api.make_request("v1/ledger", "GET", {"limit": 1})
            result["test_api_call_success"] = api_result["success"]
            if not api_result["success"]:
                result["api_error"] = api_result["error"]

            # Test mutation call specifically
            mutation_result = api.make_request("v1/mutation", "GET", {"limit": 1})
            result["mutation_call_success"] = mutation_result["success"]
            if not mutation_result["success"]:
                result["mutation_error"] = mutation_result["error"]
        else:
            result["session_token_error"] = "Failed to get session token"

        return {"success": True, "result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_mutation_zero():
    """Test if mutation 0 (initial balances) can be retrieved via REST API"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        results = {}

        # Test 1: Try to get mutation by ID 0 directly
        try:
            result = api.make_request("v1/mutation/0", "GET")
            results["mutation_0_direct"] = {
                "success": result["success"],
                "status_code": result.get("status_code"),
                "data_preview": result.get("data", "")[:500]
                if result["success"]
                else result.get("error", ""),
            }
        except Exception as e:
            results["mutation_0_direct"] = {"error": str(e)}

        # Test 2: Try to get mutations with very early date range to catch initial balances
        try:
            # Use a very early date range that should include initial balances
            params = {"dateFrom": "1900-01-01", "dateTo": "2000-01-01", "limit": 10}
            result = api.get_mutations(params)
            results["early_date_range"] = {
                "success": result["success"],
                "status_code": result.get("status_code"),
            }

            if result["success"]:
                import json

                data = json.loads(result["data"])
                mutations = data.get("items", [])
                results["early_date_range"]["count"] = len(mutations)

                # Look for mutation 0 or very low IDs
                if mutations:
                    first_mutation = mutations[0]
                    results["early_date_range"]["first_mutation"] = {
                        "id": first_mutation.get("id"),
                        "date": first_mutation.get("date"),
                        "description": first_mutation.get("description"),
                        "all_fields": list(first_mutation.keys()),
                    }

                    # Check if any have ID 0 or very low IDs
                    low_id_mutations = [m for m in mutations if m.get("id", 999999) < 10]
                    results["early_date_range"]["low_id_mutations"] = low_id_mutations
            else:
                results["early_date_range"]["error"] = result.get("error")

        except Exception as e:
            results["early_date_range"] = {"error": str(e)}

        # Test 3: Try to get mutations without date filter to see if we get all mutations
        try:
            params = {"limit": 20}
            result = api.get_mutations(params)
            results["no_date_filter"] = {
                "success": result["success"],
                "status_code": result.get("status_code"),
            }

            if result["success"]:
                import json

                data = json.loads(result["data"])
                mutations = data.get("items", [])
                results["no_date_filter"]["count"] = len(mutations)

                if mutations:
                    # Sort by ID to see the lowest IDs
                    sorted_mutations = sorted(mutations, key=lambda x: x.get("id", 999999))
                    results["no_date_filter"]["lowest_id_mutations"] = sorted_mutations[:5]
                    results["no_date_filter"]["highest_id_mutations"] = sorted_mutations[-5:]
            else:
                results["no_date_filter"]["error"] = result.get("error")

        except Exception as e:
            results["no_date_filter"] = {"error": str(e)}

        # Test 4: Try to access mutations endpoint directly with specific parameters
        try:
            # Try with offset 0 to get the very first mutations
            params = {"limit": 50, "offset": 0}
            result = api.make_request("v1/mutation", "GET", params)
            results["offset_zero"] = {"success": result["success"], "status_code": result.get("status_code")}

            if result["success"]:
                import json

                data = json.loads(result["data"])
                mutations = data.get("items", [])
                results["offset_zero"]["count"] = len(mutations)

                if mutations:
                    # Look for mutation 0 specifically
                    mutation_zero = next((m for m in mutations if m.get("id") == 0), None)
                    results["offset_zero"]["mutation_zero_found"] = bool(mutation_zero)
                    if mutation_zero:
                        results["offset_zero"]["mutation_zero_data"] = mutation_zero

                    # Show ID range
                    ids = [m.get("id") for m in mutations if m.get("id") is not None]
                    if ids:
                        results["offset_zero"]["id_range"] = {
                            "min": min(ids),
                            "max": max(ids),
                            "all_ids": sorted(ids)[:10],  # First 10 IDs
                        }
            else:
                results["offset_zero"]["error"] = result.get("error")

        except Exception as e:
            results["offset_zero"] = {"error": str(e)}

        return {
            "success": True,
            "results": results,
            "summary": "Tested multiple approaches to find mutation 0 (initial balances)",
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_iterator_starting_point():
    """Test where the REST iterator actually starts scanning"""
    try:
        from verenigingen.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        results = {}

        # Test 1: Check if mutation 0 is accessible via iterator
        results["mutation_0_via_iterator"] = {
            "by_id": bool(iterator.fetch_mutation_by_id(0)),
            "by_detail": bool(iterator.fetch_mutation_detail(0)),
        }

        # Test 2: Check the estimate_id_range method to see where it starts looking
        range_result = iterator.estimate_id_range()
        results["estimated_range"] = range_result

        # Test 3: Check mutations 0-20 to see what's actually accessible
        results["low_id_scan"] = {}
        for test_id in range(0, 21):
            by_id = iterator.fetch_mutation_by_id(test_id)
            by_detail = iterator.fetch_mutation_detail(test_id)
            results["low_id_scan"][test_id] = {
                "by_id_found": bool(by_id),
                "by_detail_found": bool(by_detail),
                "by_id_data": by_id.get("date") if by_id else None,
                "by_detail_data": by_detail.get("date") if by_detail else None,
            }

        # Test 4: Test the actual range fetching with IDs 0-20
        results["range_fetch_test"] = {}
        try:
            mutations = iterator.fetch_all_mutations_by_range(0, 20)
            results["range_fetch_test"] = {
                "success": True,
                "count": len(mutations),
                "ids_found": [m.get("id") for m in mutations if m.get("id") is not None],
                "types_found": [m.get("type") for m in mutations if m.get("type") is not None],
                "dates_found": [m.get("date") for m in mutations if m.get("date") is not None],
            }
        except Exception as e:
            results["range_fetch_test"] = {"error": str(e)}

        return {
            "success": True,
            "results": results,
            "analysis": {
                "mutation_0_accessible": any(results["mutation_0_via_iterator"].values()),
                "estimated_start": range_result.get("lowest_id"),
                "estimated_end": range_result.get("highest_id"),
            },
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


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
                results[f"test_{i}"] = {
                    "params": params,
                    "success": True,
                    "items_count": len(data.get("items", [])),
                    "raw_sample": result["data"][:500] if len(result["data"]) > 500 else result["data"],
                }

                # If we found items, analyze the first one in detail
                if data.get("items"):
                    first_item = data["items"][0]
                    results[f"test_{i}"]["first_item_analysis"] = {
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
                results[f"test_{i}"] = {
                    "params": params,
                    "success": False,
                    "error": result.get("error"),
                    "status_code": result.get("status_code"),
                }

        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}
