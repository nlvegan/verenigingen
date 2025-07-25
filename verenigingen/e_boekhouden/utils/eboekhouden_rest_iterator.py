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
            session_url = f"{self.base_url}/v1/session"
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
                    f"Session token request failed: {response.status_code} - {response.text}",
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
            url = f"{self.base_url}/v1/mutation"
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
                        f"Failed to fetch mutation {mutation_id}: {response.status_code}",
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
            url = f"{self.base_url}/v1/mutation/{mutation_id}"
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
                url = f"{self.base_url}/v1/mutation"
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
                                    # Preserve amount field from summary if not in detailed data
                                    if "amount" not in detailed or detailed.get("amount") is None:
                                        if "amount" in mutation:
                                            detailed["amount"] = mutation["amount"]
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
                            f"Unexpected response format for type {mutation_type}", "REST Iterator"
                        )
                        break

                else:
                    frappe.log_error(
                        f"Failed to fetch mutations of type {mutation_type}: {response.status_code}",
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
                        # Preserve amount field from summary if not in detailed data
                        if "amount" not in detail_data or detail_data.get("amount") is None:
                            if "amount" in mutation_data:
                                detail_data["amount"] = mutation_data["amount"]
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
                        # Preserve amount field from summary if not in detailed data
                        if "amount" not in detail_data or detail_data.get("amount") is None:
                            if "amount" in mutation_data:
                                detail_data["amount"] = mutation_data["amount"]
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
                    f"Found {found_count} mutations total."
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
def fetch_mutations_batch(start_id=1, end_id=100):
    """Fetch a batch of mutations for testing"""
    try:
        iterator = EBoekhoudenRESTIterator()

        def progress_update(info):
            print(
                f"Progress: ID {info['current_id']}, Found: {info['found']}, Not found: {info['not_found']}"
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
