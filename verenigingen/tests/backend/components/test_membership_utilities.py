import random
from datetime import datetime

import frappe
from frappe.utils import add_days, add_months, add_years, today


class MembershipTestUtilities:
    """Utilities for creating proper membership types and related data for testing"""

    @staticmethod
    def create_membership_type_with_dues_schedule(
        name,
        period="Monthly",
        amount=100.0,
        create_item=True,
        require_approval=False,
        enforce_minimum_period=True,
    ):
        """
        Create a properly configured membership type for dues schedule system

        Args:
            name: Base name for the membership type
            period: One of Daily, Monthly, Quarterly, Biannual, Annual, Lifetime, Custom
            amount: Membership fee amount
            create_item: Whether to create linked item
            require_approval: Whether new memberships require approval
            enforce_minimum_period: Whether to enforce 1-year minimum period for this type

        Returns:
            dict: Created membership type and item (if created)
        """
        # Generate unique names
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique_name = f"{name} {timestamp}"

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": unique_name,
                "description": f"Test membership type - {name} ({period})",
                "is_active": 1,
                "amount": amount,
                "currency": "EUR",
                "require_approval": require_approval,
                "default_for_new_members": 0,
                "enforce_minimum_period": enforce_minimum_period}
        )

        # Handle custom period
        if period == "Custom":
            membership_type.billing_frequency_in_months = random.choice([2, 4, 18, 24])

        membership_type.insert(ignore_permissions=True)

        result = {"membership_type": membership_type}

        # Create item if requested
        if create_item:
            item = MembershipTestUtilities._create_membership_item(membership_type)
            result["item"] = item

        # Dues schedule system handles payment processing automatically
        # No need to create subscription plans - dues schedules are created on membership creation

        return result

    @staticmethod
    def _create_membership_item(membership_type):
        """Create an item for the membership type"""
        # Check if Membership item group exists
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Membership",
                    "parent_item_group": "All Item Groups"}
            )
            item_group.insert(ignore_permissions=True)

        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": f"MEM-{membership_type.membership_type_name}".upper().replace(" ", "-")[:140],
                "item_name": f"{membership_type.membership_type_name} Membership",
                "item_group": "Membership",
                "is_stock_item": 0,
                "include_item_in_manufacturing": 0,
                "is_sales_item": 1,
                "is_purchase_item": 0,
                "is_gift_item": 0,
                "has_variants": 0,
                "stock_uom": "Nos",
                "is_service_item": 1}
        )

        # Add item defaults
        company = frappe.defaults.get_global_default("company")
        if company:
            item.append("item_defaults", {"company": company, "default_warehouse": None})

        item.insert(ignore_permissions=True)
        return item

    # Subscription plan creation removed - dues schedule system handles payment processing

    @staticmethod
    def create_standard_membership_types():
        """Create a standard set of membership types for testing"""
        standard_types = [
            {
                "name": "Daily Test",
                "period": "Daily",
                "amount": 5.0,
                "description": "Daily membership for short-term testing"},
            {
                "name": "Monthly Basic",
                "period": "Monthly",
                "amount": 25.0,
                "description": "Basic monthly membership"},
            {
                "name": "Monthly Premium",
                "period": "Monthly",
                "amount": 50.0,
                "description": "Premium monthly membership with benefits"},
            {
                "name": "Quarterly Standard",
                "period": "Quarterly",
                "amount": 70.0,
                "description": "Standard quarterly membership"},
            {
                "name": "Annual Regular",
                "period": "Annual",
                "amount": 250.0,
                "description": "Regular annual membership"},
            {
                "name": "Annual Student",
                "period": "Annual",
                "amount": 100.0,
                "description": "Discounted annual student membership"},
            {
                "name": "Lifetime Honorary",
                "period": "Lifetime",
                "amount": 0.0,
                "description": "Honorary lifetime membership",
                "require_approval": True},
        ]

        created_types = []
        for config in standard_types:
            result = MembershipTestUtilities.create_membership_type_with_subscription(
                name=config["name"],
                period=config["period"],
                amount=config["amount"],
                require_approval=config.get("require_approval", False),
            )
            created_types.append(result)

        return created_types

    @staticmethod
    def create_membership_with_dues_schedule(
        member, membership_type, start_date=None, submit=True, custom_amount=None
    ):
        """
        Create a membership following the actual system logic

        Args:
            member: Member document or member name
            membership_type: MembershipType document or name
            start_date: Start date for the membership (defaults to today)
            submit: Whether to submit the membership (triggers dues schedule creation)
            custom_amount: Optional custom membership amount

        Returns:
            dict: Created membership and dues schedule (if created)
        """
        if isinstance(member, str):
            member = frappe.get_doc("Member", member)
        if isinstance(membership_type, str):
            membership_type = frappe.get_doc("Membership Type", membership_type)

        if not start_date:
            start_date = today()

        # Build membership data
        membership_data = {
            "doctype": "Membership",
            "member": member.name,
            "membership_type": membership_type.name,
            "start_date": start_date,
            }

        # Add custom amount if provided
        if custom_amount is not None:
            membership_data.update(
                {
                    "uses_custom_amount": 1,
                    "custom_amount": custom_amount,
                    "amount_reason": "Test custom amount"}
            )

        # Create membership
        membership = frappe.get_doc(membership_data)
        membership.insert(ignore_permissions=True)

        result = {"membership": membership}

        # Submit the membership to trigger automatic subscription creation
        # NOTE: The system may enforce a minimum 1-year membership period
        # depending on the "enforce_minimum_membership_period" setting in Verenigingen Settings
        # When enabled, renewal_date will always be at least 1 year from start_date
        if submit:
            try:
                membership.submit()
                frappe.db.commit()

                # Reload to get the auto-created dues schedule
                membership.reload()
                if membership.dues_schedule:
                    dues_schedule = frappe.get_doc("Membership Dues Schedule", membership.dues_schedule)
                    result["dues_schedule"] = dues_schedule
            except Exception as e:
                # Handle validation errors (e.g., minimum period constraint)
                frappe.log_error(f"Error submitting membership: {str(e)}")
                result["error"] = str(e)

        return result

    @staticmethod
    def _calculate_end_date(start_date, period, custom_months=None):
        """Calculate membership end date based on period"""
        if period == "Daily":
            return add_days(start_date, 1)
        elif period == "Monthly":
            return add_months(start_date, 1)
        elif period == "Quarterly":
            return add_months(start_date, 3)
        elif period == "Biannual":
            return add_months(start_date, 6)
        elif period == "Annual":
            return add_years(start_date, 1)
        elif period == "Lifetime":
            return add_years(start_date, 50)
        elif period == "Custom" and custom_months:
            return add_months(start_date, custom_months)
        else:
            return add_years(start_date, 1)  # Default to annual

    @staticmethod
    def create_membership_via_application(member, membership_type, approver_email=None, custom_amount=None):
        """
        Create a membership through the application approval process

        This mimics the real-world flow where:
        1. Member applies (already has application_status = "Pending")
        2. Application is approved
        3. Membership is created with proper invoice and dues schedule

        Args:
            member: Member document with application_status = "Pending"
            membership_type: MembershipType to assign
            approver_email: Email of approver (defaults to Administrator)
            custom_amount: Optional custom membership amount

        Returns:
            dict: Created membership, invoice, and dues schedule
        """
        from verenigingen.verenigingen.doctype.membership_application_review import (
            membership_application_review,
        )

        if not approver_email:
            approver_email = "Administrator"

        # Temporarily set the session user to the approver
        original_user = frappe.session.user
        frappe.set_user(approver_email)

        try:
            # Call the approval function
            result = membership_application_review.approve_membership_application(
                member_id=member.name,
                membership_type=membership_type.name
                if isinstance(membership_type, frappe.model.document.Document)
                else membership_type,
                custom_amount=custom_amount,
            )

            # Get the created membership
            membership = frappe.get_doc(
                "Membership",
                {
                    "member": member.name,
                    "membership_type": membership_type.name
                    if isinstance(membership_type, frappe.model.document.Document)
                    else membership_type},
            )

            response = {"membership": membership, "approval_result": result}

            # Get linked invoice if created
            if membership.dues_schedule:
                dues_schedule = frappe.get_doc("Membership Dues Schedule", membership.dues_schedule)
                response["dues_schedule"] = dues_schedule

                # Get latest invoice
                invoices = frappe.get_all(
                    "Sales Invoice",
                    filters={"subscription": subscription.name},
                    order_by="creation desc",
                    limit=1,
                )
                if invoices:
                    response["invoice"] = frappe.get_doc("Sales Invoice", invoices[0].name)

            return response

        finally:
            # Restore original user
            frappe.set_user(original_user)

    @staticmethod
    def cleanup_test_membership_types(prefix="Test"):
        """Clean up test membership types and related data"""
        # Find all test membership types
        test_types = frappe.get_all(
            "Membership Type",
            filters={"membership_type_name": ["like", f"{prefix}%"]},
            fields=["name", "subscription_plan"],
        )

        for mt in test_types:
            # Delete linked subscription plans
            if mt.subscription_plan:
                frappe.delete_doc(
                    "Subscription Plan", mt.subscription_plan, ignore_permissions=True, force=True
                )

            # Delete linked items
            items = frappe.get_all("Item", filters={"item_name": ["like", f"{mt.name}%"]}, fields=["name"])
            for item in items:
                frappe.delete_doc("Item", item.name, ignore_permissions=True, force=True)

            # Delete membership type
            frappe.delete_doc("Membership Type", mt.name, ignore_permissions=True, force=True)

        frappe.db.commit()
        return len(test_types)

    @staticmethod
    def with_minimum_period_disabled(membership_type_names=None):
        """
        Context manager to temporarily disable minimum membership period enforcement for specific membership types

        Args:
            membership_type_names: List of membership type names to disable enforcement for,
                                 or None to disable for all membership types

        Usage:
            with MembershipTestUtilities.with_minimum_period_disabled(["Test Monthly", "Test Daily"]):
                # Create memberships with actual periods (daily, monthly, etc.)
                membership = create_membership_with_subscription(...)
        """

        class MinimumPeriodDisabler:
            def __init__(self, membership_type_names):
                self.membership_type_names = membership_type_names
                self.original_values = {}

            def __enter__(self):
                # Get membership types to modify
                if self.membership_type_names:
                    membership_types = self.membership_type_names
                else:
                    # Get all membership types
                    membership_types = frappe.get_all("Membership Type", pluck="name")

                # Store original values and disable enforcement
                for mt_name in membership_types:
                    try:
                        mt = frappe.get_doc("Membership Type", mt_name)
                        self.original_values[mt_name] = mt.get("enforce_minimum_period", True)
                        mt.db_set("enforce_minimum_period", 0, update_modified=False)
                    except Exception:
                        # Skip if membership type doesn't exist
                        pass

                frappe.db.commit()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                # Restore original values
                for mt_name, original_value in self.original_values.items():
                    try:
                        mt = frappe.get_doc("Membership Type", mt_name)
                        mt.db_set("enforce_minimum_period", original_value, update_modified=False)
                    except Exception:
                        # Skip if membership type doesn't exist
                        pass

                frappe.db.commit()

        return MinimumPeriodDisabler(membership_type_names)
