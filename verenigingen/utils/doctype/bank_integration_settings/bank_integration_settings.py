# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BankIntegrationSettings(Document):
    """Bank Integration Settings for PSD2 API connections"""

    def validate(self):
        """Validate settings before save"""
        self.validate_api_endpoint()
        self.validate_timeout_settings()

    def validate_api_endpoint(self):
        """Validate API endpoint format"""
        if self.api_endpoint:
            if not self.api_endpoint.startswith(("http://", "https://")):
                frappe.throw("API Endpoint must start with http:// or https://")

    def validate_timeout_settings(self):
        """Validate timeout and retry settings"""
        if self.timeout_seconds and self.timeout_seconds < 5:
            frappe.throw("Timeout must be at least 5 seconds")

        if self.retry_attempts and self.retry_attempts < 0:
            frappe.throw("Retry attempts cannot be negative")

        if self.rate_limit_per_minute and self.rate_limit_per_minute < 1:
            frappe.throw("Rate limit must be at least 1 request per minute")

    def test_connection(self):
        """Test bank API connection"""
        try:
            from verenigingen.utils.bank_integration import BankAPIClient

            client = BankAPIClient()
            result = client.fetch_statements(frappe.utils.today())

            if result.get("success"):
                self.connection_status = "Connected"
                self.last_error = ""
                frappe.msgprint("✅ Connection successful!", title="Bank API Test")
            else:
                self.connection_status = "Error"
                self.last_error = result.get("error", "Unknown error")
                frappe.msgprint(f"❌ Connection failed: {self.last_error}", title="Bank API Test")

        except Exception as e:
            self.connection_status = "Error"
            self.last_error = str(e)
            frappe.msgprint(f"❌ Connection error: {str(e)}", title="Bank API Test")

        self.save()

    def refresh_token(self):
        """Refresh OAuth2 access token"""
        if not all([self.client_id, self.client_secret, self.token_url]):
            frappe.throw("OAuth2 credentials required for token refresh")

        try:
            import requests

            token_data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }

            response = requests.post(self.token_url, data=token_data, timeout=30)

            if response.status_code == 200:
                token_info = response.json()
                self.access_token = token_info.get("access_token")
                self.connection_status = "Connected"
                self.last_error = ""
                frappe.msgprint("✅ Token refreshed successfully!", title="OAuth2 Token Refresh")
            else:
                self.connection_status = "Authentication Failed"
                self.last_error = f"Token refresh failed: {response.status_code}"
                frappe.msgprint(
                    f"❌ Token refresh failed: {response.status_code}", title="OAuth2 Token Refresh"
                )

        except Exception as e:
            self.connection_status = "Error"
            self.last_error = str(e)
            frappe.msgprint(f"❌ Token refresh error: {str(e)}", title="OAuth2 Token Refresh")

        self.save()


@frappe.whitelist()
def test_bank_connection():
    """Test bank API connection from client side"""
    settings = frappe.get_single("Bank Integration Settings")
    settings.test_connection()
    return {"status": settings.connection_status, "error": settings.last_error}


@frappe.whitelist()
def refresh_oauth_token():
    """Refresh OAuth2 token from client side"""
    settings = frappe.get_single("Bank Integration Settings")
    settings.refresh_token()
    return {"status": settings.connection_status, "error": settings.last_error}
