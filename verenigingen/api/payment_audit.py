import json
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, flt, today


@frappe.whitelist(allow_guest=True)
def audit_mollie_payments(start_date=None, end_date=None, detailed=True):
    """
    Audit Mollie payments against our database records

    Args:
        start_date (str): Start date for payment search (YYYY-MM-DD)
        end_date (str): End date for payment search (YYYY-MM-DD)
        detailed (bool): Include detailed payment information

    Returns:
        dict: Comprehensive audit report with statistics and discrepancies
    """

    try:
        # Set default date range if not provided (last 90 days)
        if not start_date:
            start_date = add_days(today(), -90)
        if not end_date:
            end_date = today()

        frappe.set_user("Administrator")

        # Get Mollie settings and client
        mollie_settings = frappe.get_single("Mollie Settings")
        if not mollie_settings or not mollie_settings.get_active_api_key():
            return {"success": False, "message": "Mollie settings not configured"}

        client = mollie_settings.get_mollie_client()

        # Initialize audit report
        audit_report = {
            "success": True,
            "audit_period": {
                "start_date": start_date,
                "end_date": end_date,
                "days_covered": (
                    datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")
                ).days,
            },
            "mollie_payments": {"total_count": 0, "successful_count": 0, "total_amount": 0.0, "payments": []},
            "database_payments": {
                "total_count": 0,
                "successful_count": 0,
                "total_amount": 0.0,
                "payments": [],
            },
            "discrepancies": {
                "missing_in_db": [],
                "missing_in_mollie": [],
                "amount_mismatches": [],
                "status_mismatches": [],
            },
            "summary": {
                "payments_matched": 0,
                "payments_missing_in_db": 0,
                "payments_missing_in_mollie": 0,
                "amount_differences": 0,
                "total_amount_difference": 0.0,
            },
        }

        print(f"🔍 Starting payment audit for period: {start_date} to {end_date}")

        # Step 1: Get all successful payments from Mollie API
        print("📡 Fetching payments from Mollie API...")
        mollie_payments = fetch_mollie_payments(client, start_date, end_date)
        audit_report["mollie_payments"]["total_count"] = len(mollie_payments)

        successful_mollie_payments = [p for p in mollie_payments if p.get("status") == "paid"]
        audit_report["mollie_payments"]["successful_count"] = len(successful_mollie_payments)
        audit_report["mollie_payments"]["total_amount"] = sum(
            float(p.get("amount", {}).get("value", 0)) for p in successful_mollie_payments
        )

        if detailed:
            audit_report["mollie_payments"]["payments"] = successful_mollie_payments

        print(f"   Found {len(mollie_payments)} total payments, {len(successful_mollie_payments)} successful")

        # Step 2: Get all payments from our database
        print("🗄️ Fetching payments from database...")
        db_payments = fetch_database_payments(start_date, end_date)
        audit_report["database_payments"]["total_count"] = len(db_payments)

        successful_db_payments = [p for p in db_payments if p.get("payment_status") == "Completed"]
        audit_report["database_payments"]["successful_count"] = len(successful_db_payments)
        audit_report["database_payments"]["total_amount"] = sum(
            flt(p.get("amount", 0)) for p in successful_db_payments
        )

        if detailed:
            audit_report["database_payments"]["payments"] = successful_db_payments

        print(f"   Found {len(db_payments)} total database records, {len(successful_db_payments)} completed")

        # Step 3: Cross-reference and identify discrepancies
        print("🔄 Cross-referencing payments...")
        cross_reference_payments(audit_report, successful_mollie_payments, successful_db_payments)

        # Step 4: Generate summary statistics
        generate_audit_summary(audit_report)

        print("✅ Payment audit completed successfully")
        return audit_report

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Payment Audit Error")
        return {
            "success": False,
            "message": f"Payment audit failed: {str(e)}",
            "traceback": frappe.get_traceback(),
        }


def fetch_mollie_payments(client, start_date, end_date, limit=250):
    """
    Fetch payments from Mollie API for the specified date range

    Args:
        client: Mollie API client
        start_date (str): Start date (YYYY-MM-DD)
        end_date (str): End date (YYYY-MM-DD)
        limit (int): Max payments per API call

    Returns:
        list: List of Mollie payment objects
    """

    payments = []
    has_next = True
    from_param = None

    # Convert dates to ISO format for Mollie API
    start_datetime = f"{start_date}T00:00:00Z"
    end_datetime = f"{end_date}T23:59:59Z"

    try:
        while has_next:
            # Build API parameters
            params = {
                "limit": limit,
                "from": start_datetime,
                "to": end_datetime,
                "profileId": frappe.get_single("Mollie Settings").profile_id,
            }

            if from_param:
                params["from"] = from_param

            # Fetch payments
            payment_list = client.payments.list(**params)

            # Filter by date range and add to results
            for payment in payment_list:
                payment_date = payment.created_at[:10]  # Extract YYYY-MM-DD
                if start_date <= payment_date <= end_date:
                    # Handle both dict and object responses from Mollie API
                    amount_value = (
                        payment.amount.value
                        if hasattr(payment.amount, "value")
                        else payment.amount.get("value")
                    )
                    amount_currency = (
                        payment.amount.currency
                        if hasattr(payment.amount, "currency")
                        else payment.amount.get("currency")
                    )

                    payments.append(
                        {
                            "id": payment.id,
                            "status": payment.status,
                            "amount": {"value": amount_value, "currency": amount_currency},
                            "created_at": payment.created_at,
                            "description": payment.description,
                            "metadata": payment.metadata or {},
                            "subscription_id": getattr(payment, "subscription_id", None),
                            "customer_id": getattr(payment, "customer_id", None),
                        }
                    )

            # Check if we need to fetch more payments
            has_next = payment_list.has_next() and len(payment_list) == limit
            if has_next:
                from_param = payment_list[-1].id

    except Exception as e:
        frappe.log_error(f"Error fetching Mollie payments: {str(e)}", "Mollie API Error")
        raise

    return payments


def fetch_database_payments(start_date, end_date):
    """
    Fetch payment records from our database

    Args:
        start_date (str): Start date (YYYY-MM-DD)
        end_date (str): End date (YYYY-MM-DD)

    Returns:
        list: List of database payment records
    """

    try:
        # Get payments from Payment History child table
        payment_history = frappe.db.sql(
            """
            SELECT
                ph.payment_id,
                ph.payment_date,
                ph.amount,
                ph.payment_status,
                ph.mollie_payment_id,
                ph.parent as donation_name,
                d.donor,
                d.mollie_customer_id,
                d.mollie_subscription_id
            FROM `tabPayment History` ph
            JOIN `tabDonation` d ON ph.parent = d.name
            WHERE ph.payment_date BETWEEN %s AND %s
            AND ph.payment_status IN ('Completed', 'Pending', 'Open')
            ORDER BY ph.payment_date DESC
        """,
            (start_date, end_date),
            as_dict=True,
        )

        # Also get direct donation payments (for non-recurring)
        donations = frappe.db.sql(
            """
            SELECT
                name as donation_name,
                payment_id,
                donation_date as payment_date,
                amount,
                payment_status,
                donor,
                mollie_customer_id,
                mollie_subscription_id
            FROM `tabDonation`
            WHERE donation_date BETWEEN %s AND %s
            AND payment_status IN ('Completed', 'Pending', 'Open')
            AND (payment_id IS NOT NULL AND payment_id != '')
            ORDER BY donation_date DESC
        """,
            (start_date, end_date),
            as_dict=True,
        )

        # Combine both sources
        all_payments = []

        # Add payment history records
        for ph in payment_history:
            all_payments.append(
                {
                    "source": "payment_history",
                    "payment_id": ph.mollie_payment_id or ph.payment_id,
                    "payment_date": str(ph.payment_date),
                    "amount": flt(ph.amount),
                    "payment_status": ph.payment_status,
                    "donation_name": ph.donation_name,
                    "donor": ph.donor,
                    "mollie_customer_id": ph.mollie_customer_id,
                    "mollie_subscription_id": ph.mollie_subscription_id,
                }
            )

        # Add direct donation records (avoid duplicates)
        payment_ids_added = {p["payment_id"] for p in all_payments if p["payment_id"]}

        for donation in donations:
            if donation.payment_id not in payment_ids_added:
                all_payments.append(
                    {
                        "source": "donation",
                        "payment_id": donation.payment_id,
                        "payment_date": str(donation.payment_date),
                        "amount": flt(donation.amount),
                        "payment_status": donation.payment_status,
                        "donation_name": donation.donation_name,
                        "donor": donation.donor,
                        "mollie_customer_id": donation.mollie_customer_id,
                        "mollie_subscription_id": donation.mollie_subscription_id,
                    }
                )

        return all_payments

    except Exception as e:
        frappe.log_error(f"Error fetching database payments: {str(e)}", "Database Query Error")
        raise


def cross_reference_payments(audit_report, mollie_payments, db_payments):
    """
    Cross-reference Mollie payments with database records to identify discrepancies
    """

    # Create lookup dictionaries
    mollie_by_id = {p["id"]: p for p in mollie_payments}
    db_by_payment_id = {p["payment_id"]: p for p in db_payments if p.get("payment_id")}

    # Find payments missing in database
    for mollie_payment in mollie_payments:
        mollie_id = mollie_payment["id"]
        if mollie_id not in db_by_payment_id:
            audit_report["discrepancies"]["missing_in_db"].append(
                {
                    "mollie_payment_id": mollie_id,
                    "amount": mollie_payment["amount"]["value"],
                    "date": mollie_payment["created_at"][:10],
                    "status": mollie_payment["status"],
                    "description": mollie_payment.get("description", ""),
                }
            )

    # Find database payments missing in Mollie (potentially refunded or canceled)
    for db_payment in db_payments:
        payment_id = db_payment.get("payment_id")
        if payment_id and payment_id not in mollie_by_id:
            audit_report["discrepancies"]["missing_in_mollie"].append(
                {
                    "database_payment_id": payment_id,
                    "amount": db_payment["amount"],
                    "date": db_payment["payment_date"],
                    "status": db_payment["payment_status"],
                    "donation": db_payment["donation_name"],
                }
            )

    # Find amount and status mismatches
    for payment_id, db_payment in db_by_payment_id.items():
        if payment_id in mollie_by_id:
            mollie_payment = mollie_by_id[payment_id]
            mollie_amount = float(mollie_payment["amount"]["value"])
            db_amount = float(db_payment["amount"])

            # Check amount mismatch (allow small rounding differences)
            if abs(mollie_amount - db_amount) > 0.01:
                audit_report["discrepancies"]["amount_mismatches"].append(
                    {
                        "payment_id": payment_id,
                        "mollie_amount": mollie_amount,
                        "database_amount": db_amount,
                        "difference": mollie_amount - db_amount,
                        "donation": db_payment["donation_name"],
                    }
                )

            # Check status mismatch
            mollie_status = "Completed" if mollie_payment["status"] == "paid" else "Pending"
            if mollie_status != db_payment["payment_status"]:
                audit_report["discrepancies"]["status_mismatches"].append(
                    {
                        "payment_id": payment_id,
                        "mollie_status": mollie_payment["status"],
                        "database_status": db_payment["payment_status"],
                        "donation": db_payment["donation_name"],
                    }
                )


def generate_audit_summary(audit_report):
    """Generate summary statistics for the audit report"""

    discrepancies = audit_report["discrepancies"]

    audit_report["summary"] = {
        "payments_matched": (
            audit_report["mollie_payments"]["successful_count"] - len(discrepancies["missing_in_db"])
        ),
        "payments_missing_in_db": len(discrepancies["missing_in_db"]),
        "payments_missing_in_mollie": len(discrepancies["missing_in_mollie"]),
        "amount_differences": len(discrepancies["amount_mismatches"]),
        "status_differences": len(discrepancies["status_mismatches"]),
        "total_amount_difference": sum(d["difference"] for d in discrepancies["amount_mismatches"]),
    }

    # Calculate data integrity percentage
    total_mollie_payments = audit_report["mollie_payments"]["successful_count"]
    if total_mollie_payments > 0:
        matched_percentage = (audit_report["summary"]["payments_matched"] / total_mollie_payments) * 100
        audit_report["summary"]["data_integrity_percentage"] = round(matched_percentage, 2)
    else:
        audit_report["summary"]["data_integrity_percentage"] = 100.0


@frappe.whitelist(allow_guest=True)
def audit_subscription_payments(customer_id=None, subscription_id=None):
    """
    Audit subscription payments for specific customer/subscription

    Args:
        customer_id (str): Mollie customer ID
        subscription_id (str): Mollie subscription ID

    Returns:
        dict: Detailed subscription payment audit
    """

    try:
        frappe.set_user("Administrator")

        mollie_settings = frappe.get_single("Mollie Settings")
        client = mollie_settings.get_mollie_client()

        # Get subscription details from Mollie
        customer = client.customers.get(customer_id)
        subscription = customer.subscriptions.get(subscription_id)

        # Get all payments for this subscription
        subscription_payments = client.subscription_payments.list(customer_id, subscription_id)

        # Get corresponding database records
        db_records = frappe.db.sql(
            """
            SELECT name, donor, amount, mollie_customer_id, mollie_subscription_id,
                   payment_status, donation_date
            FROM `tabDonation`
            WHERE mollie_customer_id = %s AND mollie_subscription_id = %s
            ORDER BY donation_date DESC
        """,
            (customer_id, subscription_id),
            as_dict=True,
        )

        return {
            "success": True,
            "subscription_details": {
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "status": subscription.status,
                "amount": subscription.amount,
                "interval": subscription.interval,
                "next_payment_date": subscription.next_payment_date,
            },
            "mollie_payments": [
                {"id": p.id, "status": p.status, "amount": p.amount.value, "created_at": p.created_at}
                for p in subscription_payments
            ],
            "database_records": db_records,
            "payment_count_mollie": len(subscription_payments),
            "payment_count_database": len(db_records),
        }

    except Exception as e:
        return {"success": False, "message": f"Subscription audit failed: {str(e)}"}


@frappe.whitelist(allow_guest=True)
def fix_missing_payments(payment_ids=None, dry_run=True):
    """
    Attempt to fix payments that exist in Mollie but are missing from database

    Args:
        payment_ids (list): List of Mollie payment IDs to process
        dry_run (bool): If True, only simulate the fixes

    Returns:
        dict: Results of the fix operation
    """

    try:
        frappe.set_user("Administrator")

        if not payment_ids:
            return {"success": False, "message": "No payment IDs provided"}

        mollie_settings = frappe.get_single("Mollie Settings")
        client = mollie_settings.get_mollie_client()

        results = {
            "success": True,
            "dry_run": dry_run,
            "processed": [],
            "errors": [],
            "summary": {"fixed": 0, "errors": 0},
        }

        for payment_id in payment_ids:
            try:
                # Get payment details from Mollie
                payment = client.payments.get(payment_id)

                if payment.status != "paid":
                    continue  # Skip non-successful payments

                # Try to find corresponding donation by metadata or description
                donation = find_matching_donation(payment)

                if donation and not dry_run:
                    # Add payment to Payment History
                    payment_entry = {
                        "payment_date": payment.created_at[:10],
                        "amount": float(payment.amount.value),
                        "payment_id": payment.id,
                        "payment_status": "Completed",
                        "mollie_payment_id": payment.id,
                    }

                    donation.append("payment_history", payment_entry)
                    donation.save()

                    results["processed"].append(
                        {
                            "payment_id": payment_id,
                            "donation": donation.name,
                            "amount": payment.amount.value,
                            "status": "FIXED" if not dry_run else "WOULD_FIX",
                        }
                    )
                    results["summary"]["fixed"] += 1

                elif donation:
                    results["processed"].append(
                        {
                            "payment_id": payment_id,
                            "donation": donation.name,
                            "amount": payment.amount.value,
                            "status": "WOULD_FIX",
                        }
                    )
                else:
                    results["errors"].append(
                        {
                            "payment_id": payment_id,
                            "error": "No matching donation found",
                            "amount": payment.amount.value,
                        }
                    )
                    results["summary"]["errors"] += 1

            except Exception as e:
                results["errors"].append({"payment_id": payment_id, "error": str(e)})
                results["summary"]["errors"] += 1

        return results

    except Exception as e:
        return {"success": False, "message": f"Fix operation failed: {str(e)}"}


def find_matching_donation(payment):
    """Find donation record that matches a Mollie payment"""

    # Try to match by customer_id and subscription_id
    if hasattr(payment, "customer_id") and hasattr(payment, "subscription_id"):
        donations = frappe.get_all(
            "Donation",
            filters={
                "mollie_customer_id": payment.customer_id,
                "mollie_subscription_id": payment.subscription_id,
            },
            limit=1,
        )
        if donations:
            return frappe.get_doc("Donation", donations[0].name)

    # Try to match by metadata
    metadata = payment.metadata or {}
    if metadata.get("donation_id"):
        try:
            return frappe.get_doc("Donation", metadata["donation_id"])
        except:
            pass

    # Try to match by amount and approximate date
    payment_date = payment.created_at[:10]
    amount = float(payment.amount.value)

    donations = frappe.db.sql(
        """
        SELECT name FROM `tabDonation`
        WHERE ABS(amount - %s) < 0.01
        AND donation_date BETWEEN DATE_SUB(%s, INTERVAL 2 DAY) AND DATE_ADD(%s, INTERVAL 2 DAY)
        AND payment_status = 'Pending'
        LIMIT 1
    """,
        (amount, payment_date, payment_date),
        as_dict=True,
    )

    if donations:
        return frappe.get_doc("Donation", donations[0].name)

    return None
