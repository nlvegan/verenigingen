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
        frappe.log_error("Session data: {{'accessToken': '***', 'source': '{session_data['source']}'}}")

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
                "error": "Session token failed: {session_response.status_code} - {session_response.text}",
            }

        token = session_response.json().get("token")

        # Try a simple GET to the base API URL with the token
        headers = {"Authorization": token, "Accept": "application/json"}

        # Test different base URLs
        test_urls = [
            "{settings.api_url}/",
            "{settings.api_url}/v1/",
            "{settings.api_url}/api/",
            "{settings.api_url}/swagger.json",
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
def debug_rest_relations_raw():
    """Get raw REST API relations response to analyze all available fields"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Get raw relations data (all relations, not filtered)
        result = api.get_relations({"limit": 10})

        if result["success"]:
            # Parse JSON response
            data = json.loads(result["data"])
            relations = data.get("items", [])

            # Analyze the structure of the first few relations
            analysis = {
                "success": True,
                "total_count": len(relations),
                "raw_response_sample": result["data"][:1500],  # First 1500 chars of raw JSON
                "first_relation_all_fields": relations[0] if relations else None,
                "all_field_names": list(relations[0].keys()) if relations else [],
                "field_analysis": {},
            }

            # Analyze each field across all relations
            if relations:
                for field_name in relations[0].keys():
                    values = [rel.get(field_name) for rel in relations[:10]]
                    non_empty_values = [v for v in values if v not in [None, "", 0]]

                    analysis["field_analysis"][field_name] = {
                        "sample_values": values,
                        "non_empty_count": len(non_empty_values),
                        "non_empty_values": non_empty_values[:5],  # First 5 non-empty
                        "has_meaningful_data": len(non_empty_values) > 0,
                    }

            return analysis
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_rest_vs_soap_same_relations():
    """Compare the same relations between REST and SOAP APIs"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        # Get SOAP relations
        from verenigingen.utils.eboekhouden_soap_api import EBoekhoudenSOAPAPI

        soap_api = EBoekhoudenSOAPAPI(settings)
        soap_result = soap_api.get_relaties()

        # Get REST relations
        rest_api = EBoekhoudenAPI(settings)
        rest_result = rest_api.get_relations({"limit": 20})

        comparison = {
            "soap_status": soap_result["success"],
            "rest_status": rest_result["success"],
        }

        if soap_result["success"] and rest_result["success"]:
            soap_relations = soap_result.get("relations", [])

            rest_data = json.loads(rest_result["data"])
            rest_relations = rest_data.get("items", [])

            # Find matching relations by ID
            matches = []
            for soap_rel in soap_relations[:5]:  # First 5 SOAP relations
                soap_id = soap_rel.get("ID")
                if soap_id:
                    # Find matching REST relation
                    rest_match = next((r for r in rest_relations if str(r.get("id")) == str(soap_id)), None)

                    if rest_match:
                        matches.append(
                            {
                                "id": soap_id,
                                "soap_data": {
                                    "bedrijf": soap_rel.get("Bedrijf", ""),
                                    "contactpersoon": soap_rel.get("Contactpersoon", ""),
                                    "email": soap_rel.get("Email", ""),
                                    "bp_type": soap_rel.get("BP", ""),
                                    "all_fields": list(soap_rel.keys()),
                                },
                                "rest_data": {
                                    "name": rest_match.get("name", ""),
                                    "companyName": rest_match.get("companyName", ""),
                                    "contactName": rest_match.get("contactName", ""),
                                    "email": rest_match.get("email", ""),
                                    "type": rest_match.get("type", ""),
                                    "all_fields": list(rest_match.keys()),
                                },
                            }
                        )

            comparison["matches"] = matches
            comparison["soap_total"] = len(soap_relations)
            comparison["rest_total"] = len(rest_relations)

        elif soap_result["success"]:
            comparison["soap_sample"] = soap_result.get("relations", [])[:3]
            comparison["rest_error"] = rest_result.get("error")

        elif rest_result["success"]:
            rest_data = json.loads(rest_result["data"])
            comparison["rest_sample"] = rest_data.get("items", [])[:3]
            comparison["soap_error"] = soap_result.get("error")

        else:
            comparison["soap_error"] = soap_result.get("error")
            comparison["rest_error"] = rest_result.get("error")

        return comparison

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_individual_relation_endpoint():
    """Test /v1/relation/{id} endpoint to see if it returns more detailed data"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # First get some relation IDs from the list endpoint
        list_result = api.get_relations({"limit": 5})
        if not list_result["success"]:
            return {"success": False, "error": "Failed to get relation list: {list_result['error']}"}

        list_data = json.loads(list_result["data"])
        relations = list_data.get("items", [])

        if not relations:
            return {"success": False, "error": "No relations found in list"}

        # Test individual relation endpoints
        individual_results = []

        for relation in relations[:3]:  # Test first 3 relations
            relation_id = relation.get("id")
            if relation_id:
                # Try to get individual relation data
                individual_result = api.make_request(f"v1/relation/{relation_id}")

                individual_data = {
                    "id": relation_id,
                    "list_data": relation,  # Data from list endpoint
                    "individual_success": individual_result["success"],
                }

                if individual_result["success"]:
                    try:
                        individual_json = json.loads(individual_result["data"])
                        individual_data["individual_data"] = individual_json
                        individual_data["individual_fields"] = (
                            list(individual_json.keys()) if isinstance(individual_json, dict) else "not_dict"
                        )

                        # Compare field counts
                        list_fields = len(relation.keys())
                        individual_fields = (
                            len(individual_json.keys()) if isinstance(individual_json, dict) else 0
                        )
                        individual_data["field_comparison"] = {
                            "list_fields": list_fields,
                            "individual_fields": individual_fields,
                            "individual_has_more": individual_fields > list_fields,
                        }

                    except json.JSONDecodeError as e:
                        individual_data["individual_data"] = individual_result["data"][:500]  # Raw response
                        individual_data["parse_error"] = str(e)
                else:
                    individual_data["individual_error"] = individual_result.get("error")
                    individual_data["individual_status_code"] = individual_result.get("status_code")

                individual_results.append(individual_data)

        return {
            "success": True,
            "message": "Tested {len(individual_results)} individual relation endpoints",
            "results": individual_results,
            "summary": {
                "list_endpoint_fields": list(relations[0].keys()) if relations else [],
                "individual_endpoints_tested": len(individual_results),
            },
        }

    except Exception as e:
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
            "message": "Created test migration: {migration.name}",
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
            "summary": "Tested {len(results['document_endpoints'])} document-related endpoints",
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
def debug_mutation_1319():
    """Debug mutation 1319 to understand memorial booking credit invoice issue"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Get mutation 1319 specifically
        result = api.make_request("v1/mutation/1319")

        if result["success"]:
            mutation_data = json.loads(result["data"])

            analysis = {
                "success": True,
                "mutation_id": 1319,
                "raw_data": mutation_data,
                "analysis": {
                    "mutation_type": mutation_data.get("type"),
                    "date": mutation_data.get("date"),
                    "description": mutation_data.get("description"),
                    "amount": mutation_data.get("amount"),
                    "debit": mutation_data.get("debit"),
                    "credit": mutation_data.get("credit"),
                    "invoice_number": mutation_data.get("invoiceNumber"),
                    "relation_id": mutation_data.get("relationId"),
                    "ledger_id": mutation_data.get("ledgerId"),
                    "is_memorial": mutation_data.get("type") == "Memorial",
                    "has_relation": bool(mutation_data.get("relationId")),
                    "has_invoice_number": bool(mutation_data.get("invoiceNumber")),
                    "amount_negative": (mutation_data.get("amount", 0) < 0),
                },
            }

            # Check if this looks like a credit invoice
            if analysis["analysis"]["is_memorial"] and analysis["analysis"]["has_relation"]:
                analysis["credit_invoice_indicators"] = {
                    "is_memorial_with_relation": True,
                    "has_invoice_number": analysis["analysis"]["has_invoice_number"],
                    "negative_amount": analysis["analysis"]["amount_negative"],
                    "recommendation": "Could be treated as credit invoice/note",
                }

            return analysis
        else:
            return {"success": False, "error": result["error"]}

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


@frappe.whitelist()
def analyze_equity_mutations():
    """Analyze equity account mutations 6738, 6352, 4595, 3698 and others"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Test equity mutations
        test_mutations = [6738, 6352, 4595, 3698]
        results = {
            "success": True,
            "mutations_tested": len(test_mutations),
            "results": [],
            "equity_analysis": {"patterns": {}, "account_types": {}, "import_issues": []},
        }

        for mutation_id in test_mutations:
            # Get mutation data
            result = api.make_request("v1/mutation/{mutation_id}")

            if result["success"]:
                mutation_data = json.loads(result["data"])

                # Analyze the mutation
                mutation_type = mutation_data.get("type")
                invoice_number = mutation_data.get("invoiceNumber")
                relation_id = mutation_data.get("relationId")
                rows = mutation_data.get("rows", [])
                description = mutation_data.get("description", "")

                # Calculate total amount
                amount = 0
                if rows:
                    for row in rows:
                        amount += float(row.get("amount", 0))

                analysis = {
                    "mutation_id": mutation_id,
                    "mutation_type": mutation_type,
                    "invoice_number": invoice_number,
                    "relation_id": relation_id,
                    "description": description,
                    "calculated_amount": amount,
                    "row_count": len(rows),
                    "raw_data": mutation_data,
                    "account_analysis": [],
                }

                # Analyze each row's account type
                for i, row in enumerate(rows):
                    row_ledger_id = row.get("ledgerId")
                    row_amount = float(row.get("amount", 0))
                    row_description = row.get("description", "")

                    row_analysis = {
                        "row_index": i,
                        "ledger_id": row_ledger_id,
                        "amount": row_amount,
                        "description": row_description,
                    }

                    if row_ledger_id:
                        # Check if mapping exists
                        mapping_result = frappe.db.sql(
                            """SELECT erpnext_account
                               FROM `tabE-Boekhouden Ledger Mapping`
                               WHERE ledger_id = %s
                               LIMIT 1""",
                            row_ledger_id,
                        )

                        if mapping_result:
                            erpnext_account = mapping_result[0][0]
                            account_type = frappe.db.get_value("Account", erpnext_account, "account_type")
                            account_name = frappe.db.get_value("Account", erpnext_account, "account_name")

                            row_analysis.update(
                                {
                                    "erpnext_account": erpnext_account,
                                    "account_type": account_type,
                                    "account_name": account_name,
                                    "mapping_exists": True,
                                }
                            )

                            # Track account types
                            if account_type not in results["equity_analysis"]["account_types"]:
                                results["equity_analysis"]["account_types"][account_type] = 0
                            results["equity_analysis"]["account_types"][account_type] += 1
                        else:
                            row_analysis.update(
                                {
                                    "erpnext_account": None,
                                    "account_type": None,
                                    "account_name": None,
                                    "mapping_exists": False,
                                }
                            )
                            results["equity_analysis"]["import_issues"].append(
                                "Mutation {mutation_id} row {i}: Missing ledger mapping for {row_ledger_id}"
                            )

                    analysis["account_analysis"].append(row_analysis)

                # Determine current import behavior
                if mutation_type == 7:
                    if invoice_number and relation_id:
                        # Check if it would be detected as credit invoice
                        credit_invoice_detected = False
                        if rows and len(rows) > 0:
                            main_row = rows[0]
                            main_ledger_id = main_row.get("ledgerId")
                            if main_ledger_id:
                                mapping_result = frappe.db.sql(
                                    """SELECT erpnext_account
                                       FROM `tabE-Boekhouden Ledger Mapping`
                                       WHERE ledger_id = %s
                                       LIMIT 1""",
                                    main_ledger_id,
                                )
                                if mapping_result:
                                    main_account = mapping_result[0][0]
                                    main_account_type = frappe.db.get_value(
                                        "Account", main_account, "account_type"
                                    )
                                    if main_account_type in ["Receivable", "Payable"]:
                                        credit_invoice_detected = True

                        analysis["current_import_behavior"] = (
                            "Sales/Purchase Credit Note" if credit_invoice_detected else "Journal Entry"
                        )
                    else:
                        analysis["current_import_behavior"] = "Journal Entry"
                else:
                    type_mapping = {
                        1: "Purchase Invoice",
                        2: "Sales Invoice",
                        3: "Payment Entry (Customer)",
                        4: "Payment Entry (Supplier)",
                        5: "Journal Entry (Money Received)",
                        6: "Journal Entry (Money Sent)",
                        0: "Opening Balance",
                    }
                    analysis["current_import_behavior"] = type_mapping.get(mutation_type, "Journal Entry")

                # Check if this involves equity accounts
                has_equity_account = False
                for row_analysis in analysis["account_analysis"]:
                    if row_analysis.get("account_type") == "Equity":
                        has_equity_account = True
                        break

                analysis["involves_equity"] = has_equity_account

                if has_equity_account:
                    analysis[
                        "equity_issue"
                    ] = "Equity transactions may need special handling for proper financial reporting"

                results["results"].append(analysis)
            else:
                results["results"].append(
                    {"mutation_id": mutation_id, "error": result["error"], "success": False}
                )

        # Generate summary patterns
        equity_mutations = [r for r in results["results"] if r.get("involves_equity")]
        results["equity_analysis"]["patterns"] = {
            "total_equity_mutations": len(equity_mutations),
            "common_descriptions": list(
                set([r.get("description", "") for r in equity_mutations if r.get("description")])
            ),
            "mutation_types": list(set([r.get("mutation_type") for r in equity_mutations])),
            "has_invoice_numbers": len([r for r in equity_mutations if r.get("invoice_number")]),
            "has_relations": len([r for r in equity_mutations if r.get("relation_id")]),
        }

        return results

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_enhanced_memorial_logic():
    """Test the enhanced logic for Type 7 memorial bookings with mutations 1314, 1315, 1319"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Test multiple mutations
        test_mutations = [1314, 1315, 1319]
        results = {"success": True, "mutations_tested": len(test_mutations), "results": []}

        for mutation_id in test_mutations:
            # Get mutation data
            result = api.make_request("v1/mutation/{mutation_id}")

            if result["success"]:
                mutation_data = json.loads(result["data"])

                # Simulate the enhanced logic
                mutation_type = mutation_data.get("type")
                invoice_number = mutation_data.get("invoiceNumber")
                relation_id = mutation_data.get("relationId")
                rows = mutation_data.get("rows", [])

                analysis = {
                    "mutation_id": mutation_id,
                    "mutation_type": mutation_type,
                    "invoice_number": invoice_number,
                    "relation_id": relation_id,
                    "raw_data": mutation_data,
                    "enhanced_logic_test": {},
                }

                # Test the enhanced logic conditions
                if mutation_type == 7 and invoice_number and relation_id:
                    analysis["enhanced_logic_test"]["meets_basic_criteria"] = True

                    # Check amount
                    amount = 0
                    if rows:
                        for row in rows:
                            amount += float(row.get("amount", 0))

                    analysis["enhanced_logic_test"]["calculated_amount"] = amount
                    analysis["enhanced_logic_test"]["has_non_zero_amount"] = amount != 0

                    # Check account type
                    credit_invoice_detected = False
                    main_account_type = None
                    main_account = None

                    if rows and len(rows) > 0:
                        main_row = rows[0]
                        main_ledger_id = main_row.get("ledgerId")

                        if main_ledger_id:
                            mapping_result = frappe.db.sql(
                                """SELECT erpnext_account
                                   FROM `tabE-Boekhouden Ledger Mapping`
                                   WHERE ledger_id = %s
                                   LIMIT 1""",
                                main_ledger_id,
                            )

                            if mapping_result:
                                main_account = mapping_result[0][0]
                                main_account_type = frappe.db.get_value(
                                    "Account", main_account, "account_type"
                                )

                                if main_account_type in ["Receivable", "Payable"]:
                                    credit_invoice_detected = True

                    analysis["enhanced_logic_test"]["main_ledger_id"] = (
                        main_row.get("ledgerId") if rows else None
                    )
                    analysis["enhanced_logic_test"]["main_account"] = main_account
                    analysis["enhanced_logic_test"]["main_account_type"] = main_account_type
                    analysis["enhanced_logic_test"]["credit_invoice_detected"] = credit_invoice_detected

                    if credit_invoice_detected:
                        analysis["enhanced_logic_test"]["would_convert_to"] = (
                            "Sales Credit Note"
                            if main_account_type == "Receivable"
                            else "Purchase Debit Note"
                        )
                        analysis["enhanced_logic_test"][
                            "recommendation"
                        ] = f"This Type 7 memorial booking should be imported as a {analysis['enhanced_logic_test']['would_convert_to']} instead of a Journal Entry"
                    else:
                        analysis["enhanced_logic_test"]["would_convert_to"] = "Journal Entry (no change)"
                        analysis["enhanced_logic_test"][
                            "recommendation"
                        ] = "This Type 7 memorial booking would remain as a Journal Entry"
                else:
                    analysis["enhanced_logic_test"]["meets_basic_criteria"] = False
                    analysis["enhanced_logic_test"][
                        "recommendation"
                    ] = "Does not meet criteria for credit invoice conversion"

                results["results"].append(analysis)
            else:
                results["results"].append(
                    {"mutation_id": mutation_id, "error": result["error"], "success": False}
                )

        return results

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def analyze_memorial_bookings():
    """Analyze all memorial bookings to understand patterns"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Get all mutations and filter for memorial types
        result = api.get_mutations({"limit": 1000})

        if result["success"]:
            data = json.loads(result["data"])
            mutations = data.get("items", [])

            memorial_bookings = [m for m in mutations if m.get("type") == "Memorial"]

            analysis = {
                "success": True,
                "total_mutations": len(mutations),
                "total_memorial_bookings": len(memorial_bookings),
                "memorial_analysis": [],
            }

            # Analyze each memorial booking
            for memorial in memorial_bookings[:20]:  # First 20 for analysis
                memorial_analysis = {
                    "id": memorial.get("id"),
                    "date": memorial.get("date"),
                    "description": memorial.get("description"),
                    "amount": memorial.get("amount"),
                    "relation_id": memorial.get("relationId"),
                    "invoice_number": memorial.get("invoiceNumber"),
                    "ledger_id": memorial.get("ledgerId"),
                    "has_relation": bool(memorial.get("relationId")),
                    "has_invoice_number": bool(memorial.get("invoiceNumber")),
                    "negative_amount": (memorial.get("amount", 0) < 0),
                    "credit_invoice_candidate": False,
                }

                # Determine if this could be a credit invoice
                if memorial_analysis["has_relation"] and (
                    memorial_analysis["negative_amount"] or memorial_analysis["has_invoice_number"]
                ):
                    memorial_analysis["credit_invoice_candidate"] = True

                analysis["memorial_analysis"].append(memorial_analysis)

            # Summary statistics
            credit_candidates = [m for m in analysis["memorial_analysis"] if m["credit_invoice_candidate"]]
            analysis["summary"] = {
                "credit_invoice_candidates": len(credit_candidates),
                "percentage_of_memorials": (len(credit_candidates) / len(memorial_bookings) * 100)
                if memorial_bookings
                else 0,
                "patterns": {
                    "with_relations": len([m for m in analysis["memorial_analysis"] if m["has_relation"]]),
                    "with_invoice_numbers": len(
                        [m for m in analysis["memorial_analysis"] if m["has_invoice_number"]]
                    ),
                    "negative_amounts": len(
                        [m for m in analysis["memorial_analysis"] if m["negative_amount"]]
                    ),
                },
            }

            return analysis
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def analyze_payment_mutations():
    """Fetch and analyze specific payment mutations: 7833, 5473, 6217"""
    try:
        # Initialize API
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Specific mutations to analyze
        target_mutations = [7833, 5473, 6217, 3559]
        results = {
            "timestamp": frappe.utils.now(),
            "mutations": [],
            "findings": {
                "multiple_invoice_support": False,
                "invoice_reference_locations": [],
                "payment_types_found": [],
                "bank_account_patterns": [],
                "additional_fields": [],
            },
        }

        for mutation_id in target_mutations:
            try:
                # Try to get mutation by ID directly
                result = api.make_request(f"v1/mutation/{mutation_id}", "GET")

                if result["success"]:
                    mutation_data = json.loads(result["data"])

                    # Analyze the mutation
                    analysis = {
                        "id": mutation_id,
                        "success": True,
                        "type": mutation_data.get("type"),
                        "type_name": get_mutation_type_name_for_analysis(mutation_data.get("type")),
                        "date": mutation_data.get("date"),
                        "description": mutation_data.get("description", ""),
                        "invoice_number": mutation_data.get("invoiceNumber"),
                        "relation_id": mutation_data.get("relationId"),
                        "row_count": len(mutation_data.get("rows", [])),
                        "raw_data": mutation_data,
                    }

                    # Track payment types
                    if (
                        mutation_data.get("type") is not None
                        and mutation_data.get("type") not in results["findings"]["payment_types_found"]
                    ):
                        results["findings"]["payment_types_found"].append(mutation_data.get("type"))

                    # Check for invoice references
                    invoice_refs = []
                    if mutation_data.get("invoiceNumber"):
                        invoice_refs.append(
                            {"location": "main", "invoice_number": mutation_data.get("invoiceNumber")}
                        )
                        if "main_mutation" not in results["findings"]["invoice_reference_locations"]:
                            results["findings"]["invoice_reference_locations"].append("main_mutation")

                    # Analyze rows
                    rows = mutation_data.get("rows", [])
                    for i, row in enumerate(rows):
                        if row.get("invoiceNumber"):
                            invoice_refs.append(
                                {
                                    "location": f"row_{i}",
                                    "invoice_number": row.get("invoiceNumber"),
                                    "amount": row.get("amount"),
                                }
                            )
                            if "row_level" not in results["findings"]["invoice_reference_locations"]:
                                results["findings"]["invoice_reference_locations"].append("row_level")

                        # Check for bank accounts
                        if row.get("ledgerId"):
                            ledger_info = get_ledger_info_for_analysis(row.get("ledgerId"))
                            if ledger_info and "bank" in ledger_info.get("account_name", "").lower():
                                results["findings"]["bank_account_patterns"].append(
                                    {
                                        "mutation_id": mutation_id,
                                        "ledger_id": row.get("ledgerId"),
                                        "account_name": ledger_info.get("account_name"),
                                    }
                                )

                    analysis["invoice_references"] = invoice_refs
                    analysis["has_multiple_invoices"] = (
                        len(set(ref["invoice_number"] for ref in invoice_refs)) > 1
                    )

                    if analysis["has_multiple_invoices"]:
                        results["findings"]["multiple_invoice_support"] = True

                    # Check for additional fields
                    known_fields = {
                        "id",
                        "type",
                        "date",
                        "description",
                        "invoiceNumber",
                        "relationId",
                        "rows",
                        "amount",
                        "debit",
                        "credit",
                    }
                    for key in mutation_data.keys():
                        if key not in known_fields and key not in results["findings"]["additional_fields"]:
                            results["findings"]["additional_fields"].append(key)

                    results["mutations"].append(analysis)

                else:
                    results["mutations"].append(
                        {"id": mutation_id, "success": False, "error": result["error"]}
                    )

            except Exception as e:
                results["mutations"].append({"id": mutation_id, "success": False, "error": str(e)})

        # Generate summary
        successful = len([m for m in results["mutations"] if m.get("success")])

        results["summary"] = {
            "mutations_analyzed": len(results["mutations"]),
            "successful_fetches": successful,
            "failed_fetches": len(results["mutations"]) - successful,
            "key_findings": [],
        }

        # Key findings
        if results["findings"]["multiple_invoice_support"]:
            results["summary"]["key_findings"].append("✓ Multiple invoice payments are supported in the API")

            # Find examples
            multi_invoice_examples = []
            for m in results["mutations"]:
                if m.get("has_multiple_invoices"):
                    multi_invoice_examples.append(
                        {"mutation_id": m["id"], "invoice_count": len(m.get("invoice_references", []))}
                    )

            if multi_invoice_examples:
                results["summary"]["multiple_invoice_examples"] = multi_invoice_examples
        else:
            results["summary"]["key_findings"].append("✗ No multiple invoice payments found in these samples")

        if "row_level" in results["findings"]["invoice_reference_locations"]:
            results["summary"]["key_findings"].append(
                "✓ Invoice references can appear at row level (important for allocation)"
            )

        if results["findings"]["bank_account_patterns"]:
            results["summary"]["key_findings"].append(
                "✓ Bank accounts are identifiable through ledger mappings"
            )

        if results["findings"]["additional_fields"]:
            results["summary"]["key_findings"].append(
                f"✓ Additional API fields discovered: {', '.join(results['findings']['additional_fields'])}"
            )

        # Payment type analysis
        payment_types = results["findings"]["payment_types_found"]
        if 3 in payment_types or 4 in payment_types:
            results["summary"]["key_findings"].append(
                "✓ Standard payment types (3: Customer Payment, 4: Supplier Payment) found"
            )

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
    except:
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
        from verenigingen.utils.eboekhouden_soap_api import EBoekhoudenSOAPAPI

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
