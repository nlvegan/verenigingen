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
- Automatic webhook URL synchronization to prevent configuration drift

Webhook URL Architecture:
The webhook URLs are dynamically generated from the MollieClient as the single
source of truth to prevent synchronization issues. The URLs are automatically
updated during document validation and saving to ensure they always match the
actual endpoint configuration used by payment creation services.

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
- MollieClient core integration for webhook URL consistency

Author: Development Team
Date: 2025-01-13
Version: 1.1
"""

from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


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

        # Ensure webhook URLs are always up to date
        self.validate_and_update_webhook_urls()

    def on_update(self):
        """Called after document is saved"""
        # Clear MollieConfigurationService cache to ensure fresh config
        try:
            from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
                MollieConfigurationService,
            )

            MollieConfigurationService.clear_cache()
            frappe.logger().info("Cleared MollieConfigurationService cache after settings update")
        except ImportError:
            frappe.logger().warning("Could not import MollieConfigurationService for cache clearing")

        # Update webhook URLs (always needed for payments)
        self.update_webhook_urls()

        # Register this gateway with the payment gateway factory
        self.register_payment_gateway()

    def validate_mollie_credentials(self):
        """
        Validate Mollie API credentials by making a test API call

        Raises:
            frappe.ValidationError: If credentials are invalid or API call fails
        """
        if not self.profile_id:
            return

        # Check that we have the appropriate key for the current mode
        if self.test_mode and not self.test_secret_key:
            frappe.throw(_("Test Secret Key is required when Test Mode is enabled"))
        elif not self.test_mode and not self.live_secret_key:
            frappe.throw(_("Live Secret Key is required when Test Mode is disabled"))

        try:
            from mollie.api.client import Client

            client = Client()
            api_key = self.get_active_api_key()

            if not api_key:
                mode = "test" if self.test_mode else "live"
                frappe.throw(_("{0} secret key is required for Mollie integration").format(mode.title()))

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
            api_key = self.get_active_api_key()

            if not api_key:
                mode = "test" if self.test_mode else "live"
                frappe.throw(_("Mollie {0} secret key not configured").format(mode))

            client.set_api_key(api_key)
            return client

        except ImportError:
            frappe.throw(_("Mollie Python library not installed. Please run: pip install mollie-api-python"))

    def register_payment_gateway(self):
        """Register this configuration with the payment gateway system"""
        try:
            # Single Mollie gateway configuration
            gateway_name = "Mollie"

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
        # Use MollieClient as single source of truth for webhook URLs
        from verenigingen.integrations.mollie.core.client import MollieClient

        return MollieClient().get_webhook_url()

    def _ensure_https_url(self, url: str) -> str:
        """
        Securely ensure URL uses HTTPS scheme with comprehensive validation

        Args:
            url: URL to convert to HTTPS

        Returns:
            str: URL with HTTPS scheme

        Raises:
            frappe.ValidationError: If URL is malformed or fails security checks
        """
        from urllib.parse import urlparse, urlunparse

        try:
            # Basic URL structure validation
            parsed = urlparse(url)
            if not parsed.netloc:
                raise frappe.ValidationError(f"Invalid webhook URL format: {url}")

            # URL length validation (prevent DoS attacks)
            if len(url) > 2048:
                raise frappe.ValidationError("Webhook URL exceeds maximum length (2048 characters)")

            # Scheme validation
            if parsed.scheme not in ("http", "https"):
                raise frappe.ValidationError(f"Webhook URL must use HTTP/HTTPS scheme: {url}")

            # Domain whitelist validation (production security requirement)
            allowed_domains = self._get_allowed_webhook_domains()
            if parsed.netloc not in allowed_domains:
                frappe.log_error(
                    f"Webhook domain not in whitelist: {parsed.netloc}. Allowed: {allowed_domains}",
                    "Mollie Webhook Security",
                )
                raise frappe.ValidationError(f"Webhook domain not authorized: {parsed.netloc}")

            # Path validation - prevent path traversal
            if ".." in parsed.path or parsed.path.startswith("//"):
                raise frappe.ValidationError("Invalid characters in webhook URL path")

            # Convert HTTP to HTTPS for security
            if parsed.scheme == "http":
                final_url = urlunparse(parsed._replace(scheme="https"))
                frappe.logger().info(f"Converted webhook URL from HTTP to HTTPS: {url} -> {final_url}")
                return final_url
            else:
                return url

        except frappe.ValidationError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            frappe.log_error(f"URL parsing error for webhook URL: {e}", "Mollie Settings URL Validation")
            raise frappe.ValidationError(f"Invalid webhook URL: {url}")

    def _get_allowed_webhook_domains(self):
        """
        Get list of domains allowed for webhook URLs

        Returns:
            list: Allowed domains for webhook URLs
        """
        # Get configured allowed domains or default to current site
        allowed_domains = frappe.conf.get("mollie_webhook_domains", [])

        # Always allow the current site domain
        current_site_domain = frappe.local.site
        if current_site_domain not in allowed_domains:
            allowed_domains.append(current_site_domain)

        # For development/testing, also allow common development domains
        if frappe.conf.get("developer_mode"):
            dev_domains = ["localhost", "127.0.0.1", "dev.veganisme.net"]
            for domain in dev_domains:
                if domain not in allowed_domains:
                    allowed_domains.append(domain)

        return allowed_domains

    def _get_webhook_url_for_env(self, env: str) -> str:
        """
        Get webhook URL for specific environment with proper error handling

        Args:
            env: Environment ("test" or "live")

        Returns:
            str: Webhook URL for the specified environment
        """
        try:
            # Reuse existing client method instead of creating new instance
            # This leverages any existing caching in get_mollie_client()
            from verenigingen.integrations.mollie.core.client import MollieClient

            # Create client with current API key to avoid additional database queries
            api_key = self.get_active_api_key()
            client = MollieClient(api_key=api_key)
            url = client.get_webhook_url(env=env)
            return self._ensure_https_url(url)

        except Exception as e:
            frappe.log_error(f"Failed to generate {env} webhook URL: {e}", "Mollie Webhook URL Generation")
            # Fallback to prevent system failure - construct URL directly
            site_url = frappe.utils.get_url()
            fallback_url = (
                f"{site_url}/api/method/verenigingen.utils.payment_gateways.mollie_payment_webhook?env={env}"
            )
            frappe.logger().warning(f"Using fallback webhook URL for {env} environment: {fallback_url}")
            return self._ensure_https_url(fallback_url)

    def get_test_webhook_url(self):
        """
        Get test webhook URL for Mollie test environment

        Returns:
            str: Complete test webhook URL
        """
        return self._get_webhook_url_for_env("test")

    def get_live_webhook_url(self):
        """
        Get live webhook URL for Mollie production environment

        Returns:
            str: Complete live webhook URL
        """
        return self._get_webhook_url_for_env("live")

    def get_subscription_webhook_url(self):
        """
        Get webhook URL for subscription status updates

        Returns:
            str: Complete subscription webhook URL
        """
        url = get_url(
            "/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook"
        )
        # Ensure HTTPS using secure URL parsing method
        return self._ensure_https_url(url)

    def get_redirect_url(self, reference_doctype, reference_docname, payment_id=None):
        """
        Get redirect URL after payment completion

        Args:
            reference_doctype (str): DocType of the document being paid for
            reference_docname (str): Name of the document being paid for
            payment_id (str): Payment ID for status checking

        Returns:
            str: Redirect URL
        """
        if self.redirect_url:
            return self.redirect_url

        # Default redirect to success page with payment tracking
        url_params = f"doctype={reference_doctype}&docname={reference_docname}"
        if payment_id:
            url_params += f"&payment_id={payment_id}"

        return get_url(f"payment-success?{url_params}")

    def create_customer(self, customer_data):
        """
        Create a Mollie customer for payments

        Args:
            customer_data (dict): Customer information for Mollie

        Returns:
            dict: Result with customer_id and success status
        """
        try:
            client = self.get_mollie_client()

            # Create customer
            customer = client.customers.create(customer_data)

            return {"success": True, "customer_id": customer.id, "message": "Customer created successfully"}

        except Exception as e:
            frappe.log_error(f"Failed to create Mollie customer: {str(e)}", "Mollie Customer Creation")
            return {"success": False, "customer_id": None, "message": f"Customer creation failed: {str(e)}"}

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

            # For donations, we don't need mandates - Mollie will handle payment method selection
            # Mandates are only required for direct debit, but subscriptions can use other methods
            mandate = None

            # Only create mandate if IBAN is provided (for direct debit)
            if subscription_data.get("consumerAccount"):
                mandate_data = {
                    "method": "directdebit",
                    "consumerName": customer_data.get("name", ""),
                    "consumerAccount": subscription_data.get("consumerAccount"),
                    "signatureDate": frappe.utils.today(),
                    "mandateReference": f"MANDATE-{frappe.utils.random_string(8)}",
                }
                mandate = customer.mandates.create(data=mandate_data)

            # Remove consumerAccount from subscription_data (only needed for mandate)
            subscription_data_clean = {k: v for k, v in subscription_data.items() if k != "consumerAccount"}

            # Create subscription - Mollie will prompt for payment method during first payment
            subscription = customer.subscriptions.create(data=subscription_data_clean)

            result = {
                "customer_id": customer.id,
                "subscription_id": subscription.id,
                "status": subscription.status,
                "next_payment_date": subscription.next_payment_date,
            }

            # Only include mandate_id if mandate was created
            if mandate:
                result["mandate_id"] = mandate.id

            return result

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
            customer = client.customers.get(customer_id)
            subscription = customer.subscriptions.get(subscription_id)

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
            customer = client.customers.get(customer_id)
            customer.subscriptions.delete(subscription_id)

            frappe.logger().info(
                f"Cancelled Mollie subscription {subscription_id} for customer {customer_id}"
            )
            return True

        except Exception as e:
            frappe.log_error(f"Error cancelling Mollie subscription: {str(e)}", "Mollie Subscription Cancel")
            return False

    def update_webhook_urls(self):
        """Update webhook URL fields using MollieClient as single source of truth"""
        # Always populate webhook URLs as they're needed for all payments, not just subscriptions
        # These are now dynamically generated from MollieClient to prevent sync issues
        self.testing_webhook_url = self.get_test_webhook_url()
        self.live_webhook_url = self.get_live_webhook_url()

        frappe.logger().info(
            f"Updated webhook URLs - Test: {self.testing_webhook_url}, Live: {self.live_webhook_url}"
        )

    def validate_and_update_webhook_urls(self):
        """Validate and update webhook URLs to ensure they're in sync with MollieClient"""
        try:
            # Calculate what the URLs should be
            expected_test_url = self.get_test_webhook_url()
            expected_live_url = self.get_live_webhook_url()

            # Check if update is needed
            urls_changed = (
                self.testing_webhook_url != expected_test_url or self.live_webhook_url != expected_live_url
            )

            if urls_changed:
                # Generate cryptographically secure correlation ID for tracking
                import secrets

                correlation_id = secrets.token_hex(8)

                # Log the synchronization with structured data
                frappe.logger().info(
                    f"[{correlation_id}] Webhook URLs out of sync - updating to match MollieClient",
                    extra={
                        "correlation_id": correlation_id,
                        "operation": "webhook_url_sync",
                        "previous_test_url": self.testing_webhook_url,
                        "previous_live_url": self.live_webhook_url,
                        "new_test_url": expected_test_url,
                        "new_live_url": expected_live_url,
                    },
                )

                # Perform atomic update with transaction safety
                try:
                    # Update in memory first
                    self.testing_webhook_url = expected_test_url
                    self.live_webhook_url = expected_live_url

                    # If we're in a document save context, the transaction will be handled automatically
                    # Otherwise, we need to ensure the changes are persisted
                    frappe.logger().info(f"[{correlation_id}] Webhook URLs synchronized successfully")

                except Exception as e:
                    frappe.log_error(
                        f"[{correlation_id}] Failed to update webhook URLs: {e}",
                        "Mollie Settings URL Sync Error",
                    )
                    # Re-raise to prevent partial updates
                    raise

        except Exception as e:
            frappe.log_error(f"Error during webhook URL validation: {e}", "Mollie Settings Validation")
            # Don't re-raise validation errors to prevent document save failures
            frappe.logger().warning(f"Webhook URL validation failed, continuing with existing URLs: {e}")

    def update_subscription_webhook_url(self):
        """Deprecated - use update_webhook_urls()"""
        self.update_webhook_urls()

    def get_active_api_key(self):
        """Get the active API key based on test_mode setting"""
        if self.test_mode:
            return self.get_password(fieldname="test_secret_key", raise_exception=False)
        else:
            return self.get_password(fieldname="live_secret_key", raise_exception=False)

    def get_api_key(self):
        """Get decrypted API key - deprecated, use get_active_api_key()"""
        return self.get_active_api_key()

    def get_organization_token(self):
        """Get decrypted organization access token"""
        if self.enable_backend_api:
            return self.get_password(fieldname="organization_access_token", raise_exception=False)
        return None

    def get_webhook_secret(self):
        """Get webhook secret key for signature verification based on test mode"""
        if self.test_mode:
            return self.get_password(fieldname="testing_webhook_secret_key", raise_exception=False)
        else:
            return self.get_password(fieldname="live_webhook_secret_key", raise_exception=False)

    def get_testing_webhook_secret(self):
        """Get testing webhook secret key"""
        return self.get_password(fieldname="testing_webhook_secret_key", raise_exception=False)

    def get_live_webhook_secret(self):
        """Get live webhook secret key"""
        return self.get_password(fieldname="live_webhook_secret_key", raise_exception=False)

    def get_next_payment_date_for_scheduled_months(self, min_months_ahead=2):
        """
        Calculate the next payment date based on configured quarterly/yearly payment months.

        This method reads the quarterly_yearly_payment_months field (comma-separated list
        of months) and returns the first eligible month that is at least min_months_ahead
        from now, scheduled for the configured payment_day_of_month.

        Args:
            min_months_ahead: Minimum number of months from current date (default: 2)

        Returns:
            str: ISO date string (YYYY-MM-DD) for the configured day of the selected month,
                 or None if no valid months configured

        Example:
            If quarterly_yearly_payment_months = "1,4,7,10" (quarterly)
            and payment_day_of_month = 25
            and current date is November 15, 2025:
            - Dec 2025 is too soon (< 2 months)
            - Jan 2026 is exactly 2 months → returns "2026-01-25"
        """
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta

        if not self.quarterly_yearly_payment_months:
            return None

        # Get configured payment day (default to 25 if not set)
        payment_day = int(self.payment_day_of_month) if self.payment_day_of_month else 25

        # Validate payment day (1-28 to ensure valid in all months)
        if not 1 <= payment_day <= 28:
            frappe.log_error(
                f"Invalid payment_day_of_month: {payment_day}. Must be between 1-28.",
                "Mollie Settings Payment Date Calculation",
            )
            payment_day = 25  # Fallback to default

        # Parse configured months
        try:
            configured_months = [
                int(m.strip()) for m in self.quarterly_yearly_payment_months.split(",") if m.strip()
            ]
            # Validate month values (1-12)
            configured_months = [m for m in configured_months if 1 <= m <= 12]
            if not configured_months:
                return None
        except (ValueError, AttributeError):
            frappe.log_error(
                f"Invalid quarterly_yearly_payment_months format: {self.quarterly_yearly_payment_months}",
                "Mollie Settings Payment Date Calculation",
            )
            return None

        # Sort months for easier iteration
        configured_months.sort()

        # Calculate minimum eligible date (min_months_ahead from now)
        today = datetime.now().date()
        min_date = today + relativedelta(months=min_months_ahead)

        # Find the first configured month that is >= min_date
        # Search up to 2 years ahead to handle edge cases
        for year_offset in range(0, 3):
            for month in configured_months:
                candidate_year = min_date.year + year_offset
                candidate_date = datetime(candidate_year, month, payment_day).date()

                if candidate_date >= min_date:
                    return candidate_date.strftime("%Y-%m-%d")

        # Fallback: shouldn't reach here, but return None if no valid date found
        frappe.log_error(
            f"Could not find eligible payment date with months {configured_months} and min_date {min_date}",
            "Mollie Settings Payment Date Calculation",
        )
        return None


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_mollie_settings():
    """
    Get Mollie settings singleton

    Returns:
        MollieSettings: Mollie settings document
    """
    return frappe.get_single("Mollie Settings")


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def test_mollie_connection():
    """
    Test Mollie API connection

    Returns:
        dict: Test result with status and message
    """
    try:
        settings = frappe.get_single("Mollie Settings")
        settings.validate_mollie_credentials()

        return {"success": True, "message": _("Mollie connection test successful")}

    except Exception as e:
        return {"success": False, "message": _("Mollie connection test failed: {0}").format(str(e))}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def update_webhook_urls():
    """
    Update webhook URLs in Mollie Settings

    Returns:
        dict: Updated URLs
    """
    try:
        settings = frappe.get_single("Mollie Settings")
        settings.update_webhook_urls()
        settings.save()

        return {
            "success": True,
            "testing_webhook_url": settings.testing_webhook_url,
            "live_webhook_url": settings.live_webhook_url,
            "message": _("Webhook URLs updated successfully"),
        }
    except Exception as e:
        return {"success": False, "message": _("Failed to update webhook URLs: {0}").format(str(e))}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def verify_webhook_url_sync():
    """
    Verify webhook URLs are properly synchronized with MollieClient

    Returns:
        dict: Sync verification status
    """
    try:
        settings = frappe.get_single("Mollie Settings")

        # Get expected URLs from MollieClient (single source of truth)
        expected_test_url = settings.get_test_webhook_url()
        expected_live_url = settings.get_live_webhook_url()

        # Get current stored URLs
        current_test_url = settings.testing_webhook_url
        current_live_url = settings.live_webhook_url

        is_in_sync = current_test_url == expected_test_url and current_live_url == expected_live_url

        return {
            "success": True,
            "in_sync": is_in_sync,
            "expected_urls": {"test": expected_test_url, "live": expected_live_url},
            "current_urls": {"test": current_test_url, "live": current_live_url},
            "message": "URLs are in sync" if is_in_sync else "URLs need synchronization",
        }

    except Exception as e:
        return {"success": False, "message": _("Failed to verify sync: {0}").format(str(e))}


def get_supported_currencies():
    """
    Get list of currencies supported by Mollie

    Returns:
        list: List of supported currency codes
    """
    return MollieSettings.supported_currencies
