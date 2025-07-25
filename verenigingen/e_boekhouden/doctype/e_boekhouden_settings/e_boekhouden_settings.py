# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import json

import frappe
import requests
from frappe.model.document import Document
from frappe.utils import now_datetime


class EBoekhoudenSettings(Document):
    def test_connection(self):
        """Test connection to e-Boekhouden API"""
        try:
            # Step 1: Get session token using API token
            session_token = self._get_session_token()
            if not session_token:
                self.connection_status = "❌ Failed to get session token"
                self.last_tested = now_datetime()
                frappe.msgprint("Failed to get session token. Check your API token.", indicator="red")
                return False

            # Step 2: Test API call with session token
            headers = {
                "Authorization": session_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            # Test with chart of accounts (ledger) endpoint
            url = f"{self.api_url}/v1/ledger"

            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                # Check if response contains valid JSON data
                try:
                    data = response.json()
                    if "items" in data or isinstance(data, list):
                        self.connection_status = "✅ Connection Successful"
                        self.last_tested = now_datetime()
                        frappe.msgprint("Connection test successful!", indicator="green")
                        return True
                    else:
                        error_msg = "Invalid response format from API"
                        self.connection_status = f"❌ {error_msg}"
                        self.last_tested = now_datetime()
                        frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
                        return False
                except json.JSONDecodeError:
                    error_msg = "Invalid JSON response from API"
                    self.connection_status = f"❌ {error_msg}"
                    self.last_tested = now_datetime()
                    frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
                    return False
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                self.connection_status = f"❌ {error_msg}"
                self.last_tested = now_datetime()
                frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
                return False

        except requests.exceptions.Timeout:
            error_msg = "Connection timeout"
            self.connection_status = f"❌ {error_msg}"
            self.last_tested = now_datetime()
            frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
            return False

        except Exception as e:
            error_msg = str(e)
            self.connection_status = f"❌ {error_msg}"
            self.last_tested = now_datetime()
            frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
            return False

    def _get_session_token(self):
        """Get session token using API token"""
        try:
            session_url = f"{self.api_url}/v1/session"
            session_data = {
                "accessToken": self.get_password("api_token"),
                "source": self.source_application or "Verenigingen ERPNext",
            }

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

    def get_api_data(self, endpoint, method="GET", params=None):
        """Generic method to call e-Boekhouden API"""
        try:
            # Get session token first
            session_token = self._get_session_token()
            if not session_token:
                return {"success": False, "error": "Failed to get session token"}

            headers = {
                "Authorization": session_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            url = f"{self.api_url}/{endpoint}"

            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=60)
            else:
                response = requests.post(url, headers=headers, json=params, timeout=60)

            if response.status_code == 200:
                return {"success": True, "data": response.text, "raw_response": response}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:500]}"}

        except Exception as e:
            return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_connection():
    """API method to test connection"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        result = settings.test_connection()
        settings.save()
        return {"success": result}
    except Exception as e:
        frappe.log_error(f"Error testing e-Boekhouden connection: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_grootboekrekeningen():
    """Test method to fetch Chart of Accounts from e-Boekhouden"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        result = settings.get_api_data("Grootboekrekeningen")

        if result["success"]:
            return {
                "success": True,
                "message": "Successfully fetched Chart of Accounts",
                "data_preview": result["data"][:1000] + "..."
                if len(result["data"]) > 1000
                else result["data"],
            }
        else:
            return result

    except Exception as e:
        frappe.log_error(f"Error fetching Chart of Accounts: {str(e)}")
        return {"success": False, "error": str(e)}
