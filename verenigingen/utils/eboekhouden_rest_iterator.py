"""
E-Boekhouden REST API Iterator
Fetches all mutations by iterating through mutation IDs
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
import requests


class EBoekhoudenRESTIterator:
    def __init__(self, settings=None):
        if not settings:
            settings = frappe.get_single("E-Boekhouden Settings")

        self.settings = settings
        self.base_url = settings.api_url if hasattr(settings, "api_url") else "https://api.e-boekhouden.nl"
        self.api_token = settings.get_password("api_token") if hasattr(settings, "api_token") else None

        if not self.api_token:
            raise ValueError("API token is required for REST API access")

        # Session token will be obtained on first use
        self._session_token = None
        self._session_expiry = None

    def _get_session_token(self):
        """Get session token using API token"""
        # Check if we have a valid token
        if self._session_token and self._session_expiry:
            if datetime.now() < self._session_expiry:
                return self._session_token

        try:
            session_url = "{self.base_url}/v1/session"
            session_data = {
                "accessToken": self.api_token,
                "source": self.settings.source_application or "Verenigingen ERPNext",
            }

            response = requests.post(session_url, json=session_data, timeout=30)

            if response.status_code == 200:
                session_response = response.json()
                self._session_token = session_response.get("token")
                # Set expiry to 55 minutes from now (token lasts 60 minutes)
                self._session_expiry = datetime.now() + timedelta(minutes=55)
                return self._session_token
            else:
                frappe.log_error(
                    "Session token request failed: {response.status_code} - {response.text}",
                    "E-Boekhouden REST",
                )
                return None

        except Exception as e:
            frappe.log_error(f"Error getting session token: {str(e)}", "E-Boekhouden REST")
            return None

    def _get_headers(self):
        """Get headers with valid session token"""
        token = self._get_session_token()
        if not token:
            raise ValueError("Failed to obtain session token")

        return {"Authorization": token, "Accept": "application/json"}

    def fetch_mutation_by_id(self, mutation_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a specific mutation by ID using the list endpoint with id filter

        Args:
            mutation_id: The mutation ID to fetch

        Returns:
            Mutation data or None if not found
        """
        try:
            url = "{self.base_url}/v1/mutation"
            params = {"id": mutation_id}

            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)

            if response.status_code == 200:
                response_data = response.json()

                # Handle wrapped response format
                if isinstance(response_data, dict) and "items" in response_data:
                    items = response_data["items"]
                    if items and len(items) > 0:
                        # Should return the specific mutation
                        return items[0]

                return None
            else:
                if response.status_code != 404:  # Don't log 404s
                    frappe.log_error(
                        "Failed to fetch mutation {mutation_id}: {response.status_code}",
                        "E-Boekhouden REST Iterator",
                    )
                return None

        except Exception as e:
            frappe.log_error(f"Error fetching mutation {mutation_id}: {str(e)}", "E-Boekhouden REST Iterator")
            return None

    def fetch_mutation_detail(self, mutation_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed mutation data

        Args:
            mutation_id: The mutation ID to fetch

        Returns:
            Detailed mutation data or None if not found
        """
        try:
            url = "{self.base_url}/v1/mutation/{mutation_id}"
            response = requests.get(url, headers=self._get_headers(), timeout=30)

            if response.status_code == 200:
                return response.json()
            else:
                return None

        except Exception:
            return None

    def fetch_mutations_by_type(
        self, mutation_type: int, limit: int = 500, progress_callback=None
    ) -> List[Dict[str, Any]]:
        """
        Fetch all mutations of a specific type using pagination

        Args:
            mutation_type: The mutation type (0=opening, 1=PINV, 2=SINV, 3=customer payment, etc.)
            limit: Number of mutations per request (max 500)
            progress_callback: Optional callback for progress updates

        Returns:
            List of all mutations of the specified type
        """
        all_mutations = []
        offset = 0
        total_fetched = 0

        while True:
            try:
                url = "{self.base_url}/v1/mutation"
                params = {"type": mutation_type, "limit": min(limit, 500), "offset": offset}  # API max is 500

                response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)

                if response.status_code == 200:
                    response_data = response.json()

                    if isinstance(response_data, dict) and "items" in response_data:
                        batch_mutations = response_data["items"]

                        if not batch_mutations:
                            # No more mutations to fetch
                            break

                        # Get detailed data for each mutation
                        detailed_mutations = []
                        for mutation in batch_mutations:
                            mutation_id = mutation.get("id")
                            if mutation_id is not None:
                                detailed = self.fetch_mutation_detail(mutation_id)
                                if detailed:
                                    detailed_mutations.append(detailed)

                        all_mutations.extend(detailed_mutations)
                        total_fetched += len(detailed_mutations)

                        # Progress callback
                        if progress_callback:
                            progress_callback(
                                {
                                    "mutation_type": mutation_type,
                                    "batch_size": len(detailed_mutations),
                                    "total_fetched": total_fetched,
                                    "offset": offset,
                                }
                            )

                        # If we got fewer than requested, we're done
                        if len(batch_mutations) < params["limit"]:
                            break

                        offset += len(batch_mutations)

                    else:
                        frappe.log_error(
                            "Unexpected response format for type {mutation_type}", "REST Iterator"
                        )
                        break

                else:
                    frappe.log_error(
                        "Failed to fetch mutations of type {mutation_type}: {response.status_code}",
                        "REST Iterator",
                    )
                    break

            except Exception as e:
                frappe.log_error(
                    f"Error fetching mutations of type {mutation_type}: {str(e)}", "REST Iterator"
                )
                break

        return all_mutations

    def fetch_all_mutations_by_range(
        self, start_id: int, end_id: int, progress_callback=None
    ) -> List[Dict[str, Any]]:
        """
        Fetch all mutations in a given ID range

        Args:
            start_id: Starting mutation ID
            end_id: Ending mutation ID (inclusive)
            progress_callback: Optional callback function for progress updates

        Returns:
            List of mutation data
        """
        mutations = []
        found_count = 0
        not_found_count = 0
        consecutive_not_found = 0
        max_consecutive_not_found = 100  # Stop after 100 consecutive not found

        for mutation_id in range(start_id, end_id + 1):
            # First try to get from list endpoint with filter
            mutation_data = self.fetch_mutation_by_id(mutation_id)

            if mutation_data:
                # Get the real ID from the response
                real_id = mutation_data.get("id", mutation_id)

                # If we got a mutation with id=0, try the detail endpoint
                if real_id == 0 or real_id != mutation_id:
                    detail_data = self.fetch_mutation_detail(mutation_id)
                    if detail_data:
                        mutations.append(detail_data)
                        found_count += 1
                        consecutive_not_found = 0
                    else:
                        not_found_count += 1
                        consecutive_not_found += 1
                else:
                    # We got valid data from the list endpoint
                    # Try to get more details
                    detail_data = self.fetch_mutation_detail(mutation_id)
                    if detail_data:
                        mutations.append(detail_data)
                    else:
                        mutations.append(mutation_data)
                    found_count += 1
                    consecutive_not_found = 0
            else:
                not_found_count += 1
                consecutive_not_found += 1

            # Progress update
            if progress_callback and mutation_id % 50 == 0:
                progress_callback(
                    {
                        "current_id": mutation_id,
                        "found": found_count,
                        "not_found": not_found_count,
                        "total_checked": mutation_id - start_id + 1,
                    }
                )

            # Stop if we've had too many consecutive not found
            if consecutive_not_found >= max_consecutive_not_found:
                frappe.msgprint(
                    f"Stopped at ID {mutation_id} after {max_consecutive_not_found} consecutive not found. "
                    "Found {found_count} mutations total."
                )
                break

        return mutations

    def estimate_id_range(self) -> Dict[str, Any]:
        """
        Estimate the range of mutation IDs by probing

        Returns:
            Dict with estimated start and end IDs
        """
        # Start with some reasonable guesses - INCLUDE 0 for opening balances!
        test_points = [0, 1, 100, 1000, 5000, 7000, 8000, 9000, 10000, 15000, 20000]

        lowest_found = None
        highest_found = None

        # Explicitly check for mutation 0 (opening balances) FIRST
        if self.fetch_mutation_detail(0):
            lowest_found = 0

        for test_id in test_points:
            mutation = self.fetch_mutation_detail(test_id)
            if mutation:
                if lowest_found is None or test_id < lowest_found:
                    lowest_found = test_id
                if highest_found is None or test_id > highest_found:
                    highest_found = test_id

        # If we found something, search around the boundaries
        if lowest_found is not None and lowest_found > 0:
            # Search backwards from lowest to find actual start - go down to 0
            for i in range(20):
                test_id = lowest_found - (i * 10)
                if test_id < 0:  # Changed from < 1 to < 0
                    break
                if self.fetch_mutation_detail(test_id):
                    lowest_found = test_id
                else:
                    break

        if highest_found:
            # Search forward from highest to find actual end
            for i in range(50):
                test_id = highest_found + (i * 10)
                if self.fetch_mutation_detail(test_id):
                    highest_found = test_id
                else:
                    break

        return {
            "success": bool(lowest_found is not None),
            "lowest_id": lowest_found if lowest_found is not None else 1,
            "highest_id": highest_found or 10000,
            "estimated": True,
        }


# from datetime import timedelta  # Duplicate import removed


@frappe.whitelist()
def test_rest_iterator():
    """Test the REST iterator"""
    try:
        iterator = EBoekhoudenRESTIterator()

        # Test fetching a specific mutation
        print("Testing mutation fetch by ID...")

        # Try a few IDs
        for test_id in [100, 500, 1000, 5000, 7420]:
            mutation = iterator.fetch_mutation_by_id(test_id)
            if mutation:
                print(f"\nMutation {test_id} found:")
                print(f"  Type: {mutation.get('type')}")
                print(f"  Date: {mutation.get('date')}")
                print(f"  Amount: {mutation.get('amount')}")

                # Try detail fetch
                detail = iterator.fetch_mutation_detail(test_id)
                if detail:
                    print(f"  Detail has {len(detail.keys())} fields")
                    if "rows" in detail:
                        print(f"  Has {len(detail['rows'])} line items")
            else:
                print(f"\nMutation {test_id}: Not found")

        return {"success": True, "message": "See console output"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def estimate_mutation_range():
    """Estimate the range of mutation IDs"""
    try:
        iterator = EBoekhoudenRESTIterator()

        print("Estimating mutation ID range...")
        result = iterator.estimate_id_range()

        if result["success"]:
            print(f"\nEstimated range: {result['lowest_id']} to {result['highest_id']}")
            print(f"Total mutations (estimated): {result['highest_id'] - result['lowest_id'] + 1}")

            return {
                "success": True,
                "lowest_id": result["lowest_id"],
                "highest_id": result["highest_id"],
                "estimated_count": result["highest_id"] - result["lowest_id"] + 1,
            }
        else:
            return {"success": False, "error": "Could not find any mutations"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_mutation_zero():
    """Test if mutation 0 exists and the iterator range estimation works"""
    try:
        iterator = EBoekhoudenRESTIterator()

        # Test 1: Check if mutation 0 exists
        mutation_0 = iterator.fetch_mutation_detail(0)
        result = {"mutation_0_exists": bool(mutation_0), "mutation_0_data": None}

        if mutation_0:
            result["mutation_0_data"] = {
                "id": mutation_0.get("id"),
                "date": mutation_0.get("date"),
                "amount": mutation_0.get("amount"),
                "type": mutation_0.get("type"),
                "description": mutation_0.get("description"),
            }

        # Test 2: Check what the range estimator returns now
        range_result = iterator.estimate_id_range()
        result["range_estimation"] = range_result

        # Test 3: Test the explicit checks in estimate_id_range
        print("Testing estimate_id_range logic...")
        print(f"Mutation 0 exists: {bool(mutation_0)}")
        print(f"Range result: {range_result}")

        return {"success": True, "result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def debug_rest_import_issues():
    """Debug why REST import is stopping early and failing"""
    try:
        # Get the latest migration
        migration = frappe.get_all(
            "E-Boekhouden Migration",
            filters={"migration_status": ["in", ["Completed", "Failed", "In Progress"]]},
            fields=["name", "migration_status", "imported_records", "failed_records", "error_log"],
            order_by="creation desc",
            limit=1,
        )

        if not migration:
            return {"success": False, "error": "No migrations found"}

        migration = migration[0]
        # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration["name"])

        result = {
            "migration_info": {
                "name": migration["name"],
                "status": migration["migration_status"],
                "imported": migration["imported_records"],
                "failed": migration["failed_records"],
            }
        }

        # 1. Check iterator range estimation
        iterator = EBoekhoudenRESTIterator()
        range_result = iterator.estimate_id_range()
        result["iterator_range"] = range_result

        # 2. Test specific mutations around where it might be stopping
        test_points = [600, 650, 679, 680, 700, 750, 1000, 5000, 7000, 7142]
        mutation_tests = {}

        for test_id in test_points:
            mutation = iterator.fetch_mutation_detail(test_id)
            mutation_tests[test_id] = {
                "exists": bool(mutation),
                "data": mutation.get("id") if mutation else None,
                "date": mutation.get("date") if mutation else None,
                "type": mutation.get("type") if mutation else None,
            }

        result["mutation_tests"] = mutation_tests

        # 3. Check for account permission issues
        # Find Crediteuren accounts
        crediteuren_accounts = frappe.get_all(
            "Account",
            filters={
                "account_name": ["like", "%Crediteuren%"],
                "company": frappe.get_single("E-Boekhouden Settings").default_company,
            },
            fields=["name", "account_name", "account_type", "root_type"],
        )
        result["crediteuren_accounts"] = crediteuren_accounts

        # 4. Sample recent error entries from migration log
        if migration_doc.error_log:
            import json

            try:
                error_log = json.loads(migration_doc.error_log)
                # Get last 10 errors
                recent_errors = error_log[-10:] if len(error_log) > 10 else error_log
                result["recent_errors"] = recent_errors
            except Exception:
                result["recent_errors"] = "Could not parse error log"

        return {"success": True, "result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_mutation_range(start_id=650, end_id=750):
    """Test mutations around where import stopped"""
    try:
        iterator = EBoekhoudenRESTIterator()

        results = {}
        consecutive_not_found = 0

        for mutation_id in range(int(start_id), int(end_id) + 1):
            mutation = iterator.fetch_mutation_detail(mutation_id)

            if mutation:
                results[mutation_id] = {
                    "found": True,
                    "id": mutation.get("id"),
                    "date": mutation.get("date"),
                    "type": mutation.get("type"),
                    "description": mutation.get("description", "")[:50],
                }
                consecutive_not_found = 0
            else:
                results[mutation_id] = {"found": False}
                consecutive_not_found += 1

                # Check if we hit the consecutive limit
                if consecutive_not_found >= 100:
                    results[
                        "stopped_at_{mutation_id}"
                    ] = "Hit consecutive not found limit: {consecutive_not_found}"
                    break

        return {"success": True, "results": results}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def fix_crediteuren_accounts():
    """Fix Crediteuren accounts to be Payable type"""
    try:
        company = frappe.get_single("E-Boekhouden Settings").default_company

        # Find all Crediteuren accounts that are not Payable
        accounts = frappe.get_all(
            "Account",
            filters={
                "company": company,
                "account_name": ["like", "%Crediteuren%"],
                "account_type": ["!=", "Payable"],
                "is_group": 0,
            },
            fields=["name", "account_name", "account_type"],
        )

        fixed_count = 0
        for account in accounts:
            doc = frappe.get_doc("Account", account["name"])
            doc.account_type = "Payable"
            doc.root_type = "Liability"
            doc.save()
            fixed_count += 1

        return {
            "success": True,
            "fixed_count": fixed_count,
            "accounts_fixed": [acc["name"] for acc in accounts],
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def analyze_migration_issues():
    """Analyze why the REST migration stopped early and had many errors"""
    try:
        # Get the latest migration
        migration = frappe.get_all(
            "E-Boekhouden Migration",
            filters={"migration_status": "Completed"},
            fields=["name", "imported_records", "failed_records"],
            order_by="creation desc",
            limit=1,
        )[0]

        # Get the full range
        iterator = EBoekhoudenRESTIterator()
        range_result = iterator.estimate_id_range()

        if not range_result["success"]:
            return {"success": False, "error": "Could not estimate range"}

        total_range = range_result["highest_id"] - range_result["lowest_id"] + 1
        processed = 679  # From user report
        remaining = total_range - processed

        result = {
            "current_migration": migration["name"],
            "total_mutations": total_range,
            "processed_so_far": processed,
            "remaining": remaining,
            "percentage_completed": (processed / total_range) * 100,
            "range": "{range_result['lowest_id']} to {range_result['highest_id']}",
            "issues": [],
        }

        # Analyze why it stopped
        if remaining > 6000:
            result["issues"].append(
                {
                    "type": "CRITICAL",
                    "description": "Only {processed} out of {total_range} mutations processed ({result['percentage_completed']:.1f}%)",
                    "recommendation": "Need to continue migration from mutation 680",
                }
            )

        # Test mutations around where it stopped
        test_points = [675, 679, 680, 685, 700, 1000, 5000, 7000]
        mutation_tests = {}

        for test_id in test_points:
            mutation = iterator.fetch_mutation_detail(test_id)
            mutation_tests[test_id] = {
                "exists": bool(mutation),
                "type": mutation.get("type") if mutation else None,
                "date": mutation.get("date") if mutation else None,
            }

        result["mutation_availability"] = mutation_tests

        # Check if it's a consecutive not found issue
        missing_around_680 = []
        for i in range(680, 690):
            if not mutation_tests.get(i, {}).get("exists", True):
                missing_around_680.append(i)

        if len(missing_around_680) > 5:
            result["issues"].append(
                {
                    "type": "WARNING",
                    "description": "Many missing mutations around ID 680: {missing_around_680}",
                    "recommendation": "Consecutive not found limit may have been hit",
                }
            )
        else:
            result["issues"].append(
                {
                    "type": "INFO",
                    "description": "Mutations exist beyond where import stopped",
                    "recommendation": "Import logic has a bug - should continue but doesn't",
                }
            )

        # Error analysis
        if migration["failed_records"] > migration["imported_records"]:
            result["issues"].append(
                {
                    "type": "CRITICAL",
                    "description": "High failure rate: {migration['failed_records']} failed vs {migration['imported_records']} imported",
                    "recommendation": "Need to improve error handling in import logic",
                }
            )

        return {"success": True, "result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def continue_rest_import_from_680():
    """Continue the REST import from mutation 680 where it left of"""
    try:
        # Simple approach: Create a new migration and import the remaining range
        from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            start_transaction_import,
        )

        # Create a new migration document for the continuation
        new_migration = frappe.new_doc("E-Boekhouden Migration")
        new_migration.migration_name = "REST Continue from 680 - {frappe.utils.today()}"
        new_migration.company = frappe.get_single("E-Boekhouden Settings").default_company
        new_migration.migrate_accounts = 0
        new_migration.migrate_cost_centers = 0
        new_migration.migrate_customers = 1  # May find new customers
        new_migration.migrate_suppliers = 1  # May find new suppliers
        new_migration.migrate_transactions = 1
        new_migration.date_from = "2018-12-31"  # Start from opening balances
        new_migration.date_to = frappe.utils.today()
        new_migration.migration_status = "Draft"
        new_migration.save()

        # Start the full REST import
        result = start_transaction_import(new_migration.name, import_type="all")

        return {
            "success": True,
            "migration_created": new_migration.name,
            "import_result": result,
            "message": "New migration started to import remaining transactions",
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_mutation_type_filtering():
    """Test if REST API supports filtering mutations by type"""
    try:
        import requests

        iterator = EBoekhoudenRESTIterator()

        # Test various parameters on the /v1/mutation endpoint
        test_params = [
            {"type": 1},  # Test type parameter
            {"mutationType": 1},  # Test mutationType parameter
            {"category": 1},  # Test category parameter
            {"soort": 1},  # Test soort parameter (Dutch for type)
            {"kind": 1},  # Test kind parameter
        ]

        results = {}

        for params in test_params:
            try:
                url = "{iterator.base_url}/v1/mutation"
                response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

                param_name = list(params.keys())[0]
                results[param_name] = {
                    "status_code": response.status_code,
                    "success": response.status_code == 200,
                    "response_size": len(response.text) if response.text else 0,
                }

                if response.status_code == 200:
                    try:
                        data = response.json()
                        if isinstance(data, dict) and "items" in data:
                            results[param_name]["items_count"] = len(data["items"])
                            results[param_name]["sample_item"] = data["items"][0] if data["items"] else None
                    except Exception:
                        results[param_name]["parsing_error"] = True

            except Exception as e:
                results[param_name] = {"error": str(e)}

        # Also test the base endpoint without parameters
        try:
            url = "{iterator.base_url}/v1/mutation"
            response = requests.get(url, headers=iterator._get_headers(), timeout=30)
            results["no_params"] = {
                "status_code": response.status_code,
                "success": response.status_code == 200,
                "response_size": len(response.text) if response.text else 0,
            }

            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict) and "items" in data:
                        results["no_params"]["items_count"] = len(data["items"])
                        # Check if items have type field
                        if data["items"]:
                            sample = data["items"][0]
                            results["no_params"]["sample_type"] = sample.get("type")
                            results["no_params"]["sample_keys"] = list(sample.keys())
                except Exception:
                    results["no_params"]["parsing_error"] = True

        except Exception as e:
            results["no_params"] = {"error": str(e)}

        return {"success": True, "results": results}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_mutation_pagination_and_filtering():
    """Test pagination and date filtering capabilities"""
    try:
        import requests

        iterator = EBoekhoudenRESTIterator()

        tests = {}

        # Test 1: Pagination with limit/offset
        try:
            url = "{iterator.base_url}/v1/mutation"
            params = {"type": 2, "limit": 10, "offset": 0}
            response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

            tests["pagination"] = {
                "status_code": response.status_code,
                "success": response.status_code == 200,
            }

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "items" in data:
                    tests["pagination"]["items_returned"] = len(data["items"])
                    tests["pagination"]["total_available"] = data.get("total", "not_provided")
                    tests["pagination"]["has_pagination_info"] = "total" in data or "count" in data

        except Exception as e:
            tests["pagination"] = {"error": str(e)}

        # Test 2: Date filtering
        try:
            url = "{iterator.base_url}/v1/mutation"
            params = {"type": 2, "date": "[gte]2024-01-01", "limit": 5}
            response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

            tests["date_filtering"] = {
                "status_code": response.status_code,
                "success": response.status_code == 200,
            }

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "items" in data:
                    tests["date_filtering"]["items_returned"] = len(data["items"])
                    # Check if dates are actually filtered
                    if data["items"]:
                        sample_dates = [item.get("date") for item in data["items"][:3]]
                        tests["date_filtering"]["sample_dates"] = sample_dates

        except Exception as e:
            tests["date_filtering"] = {"error": str(e)}

        # Test 3: Higher limit
        try:
            url = "{iterator.base_url}/v1/mutation"
            params = {"type": 1, "limit": 500}
            response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

            tests["high_limit"] = {
                "status_code": response.status_code,
                "success": response.status_code == 200,
            }

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "items" in data:
                    tests["high_limit"]["items_returned"] = len(data["items"])
                    tests["high_limit"]["response_size_kb"] = len(response.text) / 1024

        except Exception as e:
            tests["high_limit"] = {"error": str(e)}

        # Test 4: Check for sort/order parameters
        try:
            url = "{iterator.base_url}/v1/mutation"
            params = {"type": 2, "sort": "date", "limit": 5}
            response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

            tests["sorting"] = {"status_code": response.status_code, "success": response.status_code == 200}

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "items" in data and data["items"]:
                    dates = [item.get("date") for item in data["items"] if item.get("date")]
                    tests["sorting"]["dates_in_order"] = dates
                    tests["sorting"]["appears_sorted"] = dates == sorted(dates)

        except Exception as e:
            tests["sorting"] = {"error": str(e)}

        return {"success": True, "tests": tests}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def fetch_mutations_batch(start_id=1, end_id=100):
    """Fetch a batch of mutations for testing"""
    try:
        iterator = EBoekhoudenRESTIterator()

        def progress_update(info):
            print(
                "Progress: ID {info['current_idf']}, Found: {info['found']}, Not found: {info['not_found']}"
            )

        mutations = iterator.fetch_all_mutations_by_range(
            int(start_id), int(end_id), progress_callback=progress_update
        )

        # Group by type
        by_type = {}
        for mut in mutations:
            mut_type = mut.get("type", "Unknown")
            by_type[mut_type] = by_type.get(mut_type, 0) + 1

        return {
            "success": True,
            "count": len(mutations),
            "by_type": by_type,
            "sample": mutations[0] if mutations else None,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_optimized_import_approach():
    """Test the new optimized type-based import approach"""
    try:
        iterator = EBoekhoudenRESTIterator()

        # Test fetching each mutation type
        test_types = [0, 1, 2, 3, 4, 5, 6, 7]
        type_names = {
            0: "Opening Balance",
            1: "Purchase Invoice",
            2: "Sales Invoice",
            3: "Customer Payment",
            4: "Supplier Payment",
            5: "Money Received",
            6: "Money Sent",
            7: "Journal Entry",
        }

        results = {}
        total_mutations = 0

        for mutation_type in test_types:
            try:
                # Fetch just first 10 of each type for testing
                def progress_callback(info):
                    print(f"Type {mutation_type}: Fetched {info['total_fetched']} mutations")

                mutations = iterator.fetch_mutations_by_type(
                    mutation_type, limit=10, progress_callback=progress_callback
                )

                results[mutation_type] = {
                    "type_name": type_names.get(mutation_type, "Type {mutation_type}"),
                    "count": len(mutations),
                    "sample": mutations[0] if mutations else None,
                }

                total_mutations += len(mutations)

            except Exception as e:
                results[mutation_type] = {
                    "type_name": type_names.get(mutation_type, "Type {mutation_type}"),
                    "error": str(e),
                }

        return {
            "success": True,
            "total_mutations_found": total_mutations,
            "by_type": results,
            "message": "Found {total_mutations} mutations across {len([r for r in results.values() if 'count' in r])} types",
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
