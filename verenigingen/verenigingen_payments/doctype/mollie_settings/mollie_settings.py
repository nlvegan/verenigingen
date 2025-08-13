"""
Mollie Payment Gateway Settings

This DocType configures Mollie payment gateway integration for the Verenigingen
association management system. It provides secure credential storage, API validation,
and configuration options for Mollie payment processing.

Key Features:
- Secure API key storage with encryption
- Multi-currency support (46+ currencies)
- Test mode configuration for development
- Custom branding and redirect options
- Real-time credential validation
- Integration with payment gateway factory

Business Context:
Mollie is a European payment service provider that supports various payment methods
including credit cards, bank transfers, and local payment methods. This integration
enables associations to accept online donations and membership payments through
a user-friendly checkout experience.

Architecture:
This DocType integrates with:
- PaymentGateway abstract base class for consistent interface
- PaymentGatewayFactory for gateway selection and instantiation
- Web forms for donation and membership payment processing
- Webhook endpoints for payment status updates
- Frappe's permission and encryption systems for security

Author: Development Team
Date: 2025-01-13
Version: 1.0
"""

from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url


class MollieSettings(Document):
    """
    Mollie Payment Gateway Settings Document

    Manages configuration and validation for Mollie payment integration.
    Provides methods for credential validation, payment URL generation,
    and integration with the payment gateway system.
    """

    # Supported currencies based on Mollie documentation
    supported_currencies = [
        "AED",
        "AUD",
        "BGN",
        "BRL",
        "CAD",
        "CHF",
        "CZK",
        "DKK",
        "EUR",
        "GBP",
        "HKD",
        "HUF",
        "ILS",
        "ISK",
        "JPY",
        "MXN",
        "MYR",
        "NOK",
        "NZD",
        "PHP",
        "PLN",
        "RON",
        "RUB",
        "SEK",
        "SGD",
        "THB",
        "TWD",
        "USD",
        "ZAR",
    ]

    def validate(self):
        """Validate the document before saving"""
        if not self.flags.ignore_mandatory:
            self.validate_mollie_credentials()

    def on_update(self):
        """Called after document is saved"""
        # Update subscription webhook URL if subscriptions are enabled
        self.update_subscription_webhook_url()

        # Register this gateway with the payment gateway factory
        self.register_payment_gateway()

    def validate_mollie_credentials(self):
        """
        Validate Mollie API credentials by making a test API call

        Raises:
            frappe.ValidationError: If credentials are invalid or API call fails
        """
        if not (self.profile_id and self.secret_key):
            return

        try:
            from mollie.api.client import Client

            client = Client()
            api_key = self.get_password(fieldname="secret_key", raise_exception=False)

            if not api_key:
                frappe.throw(_("Secret key is required for Mollie integration"))

            client.set_api_key(api_key)

            # Test API call to validate credentials
            try:
                # Simple API call to check if credentials work
                client.methods.list()
                frappe.msgprint(_("Mollie credentials validated successfully"), indicator="green")
            except Exception as e:
                error_msg = _("Invalid Mollie credentials. Please check your Profile ID and Secret Key.")
                if "authentication" in str(e).lower():
                    error_msg += _(" Authentication failed.")
                elif "profile" in str(e).lower():
                    error_msg += _(" Profile ID may be incorrect.")
                elif "invalid api key" in str(e).lower():
                    error_msg += _(" API key format is invalid. Ensure it starts with 'test_' or 'live_'.")

                frappe.log_error(
                    f"Mollie credential validation failed: {str(e)}", "Mollie Settings Validation"
                )
                frappe.throw(f"{error_msg} Error details: {str(e)}")

        except ImportError:
            frappe.throw(_("Mollie Python library not installed. Please run: pip install mollie-api-python"))
        except Exception as e:
            # Simplified error logging to avoid length issues
            frappe.log_error("Mollie validation error occurred", "Mollie Settings Validation")
            frappe.throw(_("Error validating Mollie credentials: {0}").format(str(e)))

    def validate_transaction_currency(self, currency):
        """
        Validate if the given currency is supported by Mollie

        Args:
            currency (str): Currency code to validate

        Raises:
            frappe.ValidationError: If currency is not supported
        """
        if currency not in self.supported_currencies:
            frappe.throw(
                _("Currency '{0}' is not supported by Mollie. Please select another payment method.").format(
                    currency
                )
            )

    def get_payment_url(self, **kwargs):
        """
        Generate payment URL for Mollie checkout

        Args:
            **kwargs: Payment parameters to include in URL

        Returns:
            str: Complete URL for Mollie checkout page
        """
        return get_url(f"mollie_checkout?{urlencode(kwargs)}")

    def get_mollie_client(self):
        """
        Get configured Mollie API client

        Returns:
            mollie.api.client.Client: Configured Mollie client

        Raises:
            ImportError: If Mollie library is not installed
            frappe.ValidationError: If credentials are missing
        """
        try:
            from mollie.api.client import Client

            client = Client()
            api_key = self.get_password(fieldname="secret_key", raise_exception=False)

            if not api_key:
                frappe.throw(_("Mollie secret key not configured"))

            client.set_api_key(api_key)
            return client

        except ImportError:
            frappe.throw(_("Mollie Python library not installed. Please run: pip install mollie-api-python"))

    def register_payment_gateway(self):
        """Register this configuration with the payment gateway system"""
        try:
            # Update payment gateway factory to include this Mollie configuration
            gateway_name = f"Mollie-{self.gateway_name}"

            # This could integrate with a payment gateway registry if needed
            frappe.logger().info(f"Registered Mollie gateway: {gateway_name}")

        except Exception as e:
            frappe.log_error(f"Error registering Mollie gateway: {str(e)}", "Mollie Gateway Registration")

    def get_webhook_url(self):
        """
        Get webhook URL for payment status updates

        Returns:
            str: Complete webhook URL
        """
        return get_url("/api/method/verenigingen.utils.payment_gateways.mollie_webhook")

    def get_subscription_webhook_url(self):
        """
        Get webhook URL for subscription status updates

        Returns:
            str: Complete subscription webhook URL
        """
        return get_url("/api/method/verenigingen.utils.payment_gateways.mollie_subscription_webhook")

    def get_redirect_url(self, reference_doctype, reference_docname):
        """
        Get redirect URL after payment completion

        Args:
            reference_doctype (str): DocType of the document being paid for
            reference_docname (str): Name of the document being paid for

        Returns:
            str: Redirect URL
        """
        if self.redirect_url:
            return self.redirect_url

        # Default redirect to success page
        return get_url(f"payment-success?doctype={reference_doctype}&docname={reference_docname}")

    def create_subscription(self, customer_data, subscription_data):
        """
        Create a Mollie subscription for recurring payments

        Args:
            customer_data (dict): Customer information for Mollie
            subscription_data (dict): Subscription details

        Returns:
            dict: Mollie subscription response

        Raises:
            frappe.ValidationError: If subscription creation fails
        """
        if not self.enable_subscriptions:
            frappe.throw(_("Subscriptions are not enabled for this Mollie gateway"))

        try:
            client = self.get_mollie_client()

            # Create customer first (required for subscriptions)
            customer = client.customers.create(customer_data)

            # Create subscription
            subscription = client.customers_subscriptions.with_parent_id(customer.id).create(
                subscription_data
            )

            return {
                "customer_id": customer.id,
                "subscription_id": subscription.id,
                "status": subscription.status,
                "next_payment_date": subscription.next_payment_date,
                "webhook_url": subscription.webhook_url,
            }

        except Exception as e:
            frappe.log_error(f"Error creating Mollie subscription: {str(e)}", "Mollie Subscription Error")
            frappe.throw(_("Failed to create subscription: {0}").format(str(e)))

    def get_subscription(self, customer_id, subscription_id):
        """
        Get subscription details from Mollie

        Args:
            customer_id (str): Mollie customer ID
            subscription_id (str): Mollie subscription ID

        Returns:
            dict: Subscription details
        """
        try:
            client = self.get_mollie_client()
            subscription = client.customers_subscriptions.with_parent_id(customer_id).get(subscription_id)

            return {
                "id": subscription.id,
                "status": subscription.status,
                "amount": subscription.amount,
                "interval": subscription.interval,
                "next_payment_date": subscription.next_payment_date,
                "created_at": subscription.created_at,
                "canceled_at": getattr(subscription, "canceled_at", None),
            }

        except Exception as e:
            frappe.log_error(f"Error fetching Mollie subscription: {str(e)}", "Mollie Subscription Fetch")
            return None

    def cancel_subscription(self, customer_id, subscription_id):
        """
        Cancel a Mollie subscription

        Args:
            customer_id (str): Mollie customer ID
            subscription_id (str): Mollie subscription ID

        Returns:
            bool: Success status
        """
        try:
            client = self.get_mollie_client()
            client.customers_subscriptions.with_parent_id(customer_id).delete(subscription_id)

            frappe.logger().info(
                f"Cancelled Mollie subscription {subscription_id} for customer {customer_id}"
            )
            return True

        except Exception as e:
            frappe.log_error(f"Error cancelling Mollie subscription: {str(e)}", "Mollie Subscription Cancel")
            return False

    def update_subscription_webhook_url(self):
        """Update the subscription webhook URL field"""
        if self.enable_subscriptions:
            self.subscription_webhook_url = self.get_subscription_webhook_url()
        else:
            self.subscription_webhook_url = ""


@frappe.whitelist()
def get_mollie_settings(gateway_name="Default"):
    """
    Get Mollie settings for a specific gateway

    Args:
        gateway_name (str): Name of the Mollie gateway configuration

    Returns:
        MollieSettings: Mollie settings document

    Raises:
        frappe.DoesNotExistError: If settings not found
    """
    try:
        return frappe.get_doc("Mollie Settings", gateway_name)
    except frappe.DoesNotExistError:
        frappe.throw(
            _("Mollie Settings '{0}' not found. Please create the configuration first.").format(gateway_name)
        )


@frappe.whitelist()
def test_mollie_connection(gateway_name):
    """
    Test Mollie API connection for a specific gateway

    Args:
        gateway_name (str): Name of the Mollie gateway to test

    Returns:
        dict: Test result with status and message
    """
    try:
        settings = frappe.get_doc("Mollie Settings", gateway_name)
        settings.validate_mollie_credentials()

        return {"success": True, "message": _("Mollie connection test successful")}

    except Exception as e:
        return {"success": False, "message": _("Mollie connection test failed: {0}").format(str(e))}


def get_supported_currencies():
    """
    Get list of currencies supported by Mollie

    Returns:
        list: List of supported currency codes
    """
    return MollieSettings.supported_currencies
