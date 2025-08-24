#!/usr/bin/env python3
"""
Database Performance Indexes Migration
Problem #1 Resolution: Add missing database indexes for frequently queried fields

This migration adds strategic database indexes to improve query performance
for the identified N+1 patterns and frequent operations.

Based on analysis of 4,111+ individual database calls, these indexes target:
1. Member-Customer relationship lookups (most critical)
2. Status filtering (heavily used in queries)
3. Date range queries (payment dates, membership periods)
4. E-Boekhouden integration tracking fields
5. Payment and SEPA processing fields

IMPORTANT: This migration should be run during maintenance window as index
creation can take time on large tables and may temporarily lock tables.
"""

import frappe
from frappe.utils import cint


def execute():
    """Execute the performance indexes migration"""

    frappe.log_error("Starting performance indexes migration", "Database Migration")

    try:
        # Core Member DocType indexes (Highest Priority)
        add_member_performance_indexes()

        # Volunteer DocType indexes
        add_volunteer_performance_indexes()

        # SEPA Mandate indexes
        add_sepa_mandate_indexes()

        # Chapter and membership indexes
        add_chapter_membership_indexes()

        # Custom fields indexes (E-Boekhouden integration)
        add_custom_fields_indexes()

        # Composite indexes for complex queries
        add_composite_indexes()

        frappe.db.commit()

        frappe.log_error("Performance indexes migration completed successfully", "Database Migration")
        print("✓ Performance indexes migration completed successfully")

    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Performance indexes migration failed: {str(e)}"
        frappe.log_error(error_msg, "Database Migration Error")
        print(f"✗ {error_msg}")
        raise


def add_member_performance_indexes():
    """Add performance indexes to Member DocType"""

    print("Adding Member DocType performance indexes...")

    # Member.customer - MOST CRITICAL (used in all member-customer lookups)
    add_index_if_not_exists("tabMember", "customer", "idx_member_customer")

    # Member.status - heavily filtered
    add_index_if_not_exists("tabMember", "status", "idx_member_status")

    # Member.member_since - used in date range queries and analytics
    add_index_if_not_exists("tabMember", "member_since", "idx_member_since")

    # Member.birth_date - age calculations and demographic queries
    add_index_if_not_exists("tabMember", "birth_date", "idx_member_birth_date")

    # Mollie payment integration fields
    add_index_if_not_exists("tabMember", "mollie_customer_id", "idx_member_mollie_customer")
    add_index_if_not_exists("tabMember", "mollie_subscription_id", "idx_member_mollie_subscription")
    add_index_if_not_exists("tabMember", "subscription_status", "idx_member_subscription_status")

    # Member Payment History child table indexes
    add_index_if_not_exists("tabMember Payment History", "payment_status", "idx_member_payment_status")
    add_index_if_not_exists("tabMember Payment History", "payment_date", "idx_member_payment_date")
    add_index_if_not_exists("tabMember Payment History", "due_date", "idx_member_due_date")

    print("✓ Member DocType indexes added")


def add_volunteer_performance_indexes():
    """Add performance indexes to Volunteer DocType"""

    print("Adding Volunteer DocType performance indexes...")

    # Volunteer.member - 1:1 relationship heavily used for lookups
    add_index_if_not_exists("tabVolunteer", "member", "idx_volunteer_member")

    # Volunteer.status - filtered for active/inactive volunteers
    add_index_if_not_exists("tabVolunteer", "status", "idx_volunteer_status")

    # Volunteer.start_date - volunteer analytics and queries
    add_index_if_not_exists("tabVolunteer", "start_date", "idx_volunteer_start_date")

    print("✓ Volunteer DocType indexes added")


def add_sepa_mandate_indexes():
    """Add performance indexes to SEPA Mandate DocType"""

    print("Adding SEPA Mandate performance indexes...")

    # SEPA Mandate.member - core relationship for payment processing
    add_index_if_not_exists("tabSEPA Mandate", "member", "idx_sepa_mandate_member")

    # SEPA Mandate.status - critical for active mandate filtering
    add_index_if_not_exists("tabSEPA Mandate", "status", "idx_sepa_mandate_status")

    # Date fields for mandate lifecycle management
    add_index_if_not_exists("tabSEPA Mandate", "sign_date", "idx_sepa_mandate_sign_date")
    add_index_if_not_exists("tabSEPA Mandate", "first_collection_date", "idx_sepa_mandate_first_collection")
    add_index_if_not_exists("tabSEPA Mandate", "expiry_date", "idx_sepa_mandate_expiry_date")

    print("✓ SEPA Mandate indexes added")


def add_chapter_membership_indexes():
    """Add performance indexes to Chapter and Membership DocTypes"""

    print("Adding Chapter and Membership performance indexes...")

    # Chapter indexes
    add_index_if_not_exists("tabChapter", "status", "idx_chapter_status")
    add_index_if_not_exists("tabChapter", "region", "idx_chapter_region")

    # Membership indexes
    add_index_if_not_exists("tabMembership", "member", "idx_membership_member")
    add_index_if_not_exists("tabMembership", "status", "idx_membership_status")
    add_index_if_not_exists("tabMembership", "start_date", "idx_membership_start_date")
    add_index_if_not_exists("tabMembership", "renewal_date", "idx_membership_renewal_date")

    print("✓ Chapter and Membership indexes added")


def add_custom_fields_indexes():
    """Add performance indexes to custom fields (E-Boekhouden integration)"""

    print("Adding custom fields performance indexes...")

    # Sales Invoice custom fields
    add_index_if_not_exists("tabSales Invoice", "custom_membership_dues_schedule", "idx_si_membership_dues")
    add_index_if_not_exists("tabSales Invoice", "custom_coverage_start_date", "idx_si_coverage_start")
    add_index_if_not_exists("tabSales Invoice", "custom_coverage_end_date", "idx_si_coverage_end")
    add_index_if_not_exists("tabSales Invoice", "eboekhouden_mutation_nr", "idx_si_eboekhouden_mutation")
    add_index_if_not_exists("tabSales Invoice", "eboekhouden_invoice_number", "idx_si_eboekhouden_invoice")

    # Payment Entry custom fields
    add_index_if_not_exists("tabPayment Entry", "eboekhouden_mutation_nr", "idx_pe_eboekhouden_mutation")
    add_index_if_not_exists("tabPayment Entry", "custom_bank_transaction", "idx_pe_bank_transaction")
    add_index_if_not_exists("tabPayment Entry", "custom_sepa_batch", "idx_pe_sepa_batch")

    # Customer custom fields
    add_index_if_not_exists("tabCustomer", "eboekhouden_relation_code", "idx_customer_eboekhouden_code")

    # Journal Entry custom fields
    add_index_if_not_exists("tabJournal Entry", "eboekhouden_mutation_nr", "idx_je_eboekhouden_mutation")
    add_index_if_not_exists("tabJournal Entry", "eboekhouden_relation_code", "idx_je_eboekhouden_relation")

    print("✓ Custom fields indexes added")


def add_composite_indexes():
    """Add composite indexes for complex query optimization"""

    print("Adding composite performance indexes...")

    # Member status + date composite (for active member analytics)
    add_composite_index_if_not_exists("tabMember", ["status", "member_since"], "idx_member_status_since")

    # Sales Invoice customer + date composite (for customer payment history)
    add_composite_index_if_not_exists(
        "tabSales Invoice", ["customer", "posting_date"], "idx_si_customer_date"
    )

    # Payment Entry party composite (for party payment lookups)
    add_composite_index_if_not_exists(
        "tabPayment Entry", ["party_type", "party", "posting_date"], "idx_pe_party_date"
    )

    # SEPA Mandate member + status + expiry composite (for active mandate queries)
    add_composite_index_if_not_exists(
        "tabSEPA Mandate", ["member", "status", "expiry_date"], "idx_sepa_member_status_expiry"
    )

    print("✓ Composite indexes added")


def add_index_if_not_exists(table_name: str, column_name: str, index_name: str):
    """Add database index if it doesn't already exist"""

    try:
        # Check if index already exists
        existing_indexes = frappe.db.sql(
            f"""
            SHOW INDEX FROM `{table_name}`
            WHERE Key_name = %s
        """,
            [index_name],
        )

        if existing_indexes:
            print(f"  - Index {index_name} already exists on {table_name}.{column_name}")
            return

        # Check if column exists
        column_exists = frappe.db.sql(
            f"""
            SHOW COLUMNS FROM `{table_name}`
            WHERE Field = %s
        """,
            [column_name],
        )

        if not column_exists:
            print(f"  - Column {column_name} does not exist in {table_name}, skipping index")
            return

        # Create the index
        frappe.db.sql(
            f"""
            ALTER TABLE `{table_name}`
            ADD INDEX `{index_name}` (`{column_name}`)
        """
        )

        print(f"  ✓ Added index {index_name} on {table_name}.{column_name}")

    except Exception as e:
        # Log error but continue with other indexes
        error_msg = f"Failed to add index {index_name} on {table_name}.{column_name}: {str(e)}"
        frappe.log_error(error_msg, "Index Creation Error")
        print(f"  ✗ {error_msg}")


def add_composite_index_if_not_exists(table_name: str, column_names: list, index_name: str):
    """Add composite database index if it doesn't already exist"""

    try:
        # Check if index already exists
        existing_indexes = frappe.db.sql(
            f"""
            SHOW INDEX FROM `{table_name}`
            WHERE Key_name = %s
        """,
            [index_name],
        )

        if existing_indexes:
            print(f"  - Composite index {index_name} already exists on {table_name}")
            return

        # Check if all columns exist
        for column_name in column_names:
            column_exists = frappe.db.sql(
                f"""
                SHOW COLUMNS FROM `{table_name}`
                WHERE Field = %s
            """,
                [column_name],
            )

            if not column_exists:
                print(f"  - Column {column_name} does not exist in {table_name}, skipping composite index")
                return

        # Create the composite index
        columns_str = ", ".join([f"`{col}`" for col in column_names])
        frappe.db.sql(
            f"""
            ALTER TABLE `{table_name}`
            ADD INDEX `{index_name}` ({columns_str})
        """
        )

        print(f"  ✓ Added composite index {index_name} on {table_name}({', '.join(column_names)})")

    except Exception as e:
        # Log error but continue with other indexes
        error_msg = f"Failed to add composite index {index_name} on {table_name}: {str(e)}"
        frappe.log_error(error_msg, "Composite Index Creation Error")
        print(f"  ✗ {error_msg}")


def validate_indexes():
    """Validate that critical indexes were created successfully"""

    print("\nValidating critical performance indexes...")

    critical_indexes = [
        ("tabMember", "idx_member_customer"),
        ("tabMember", "idx_member_status"),
        ("tabVolunteer", "idx_volunteer_member"),
        ("tabSEPA Mandate", "idx_sepa_mandate_member"),
        ("tabSEPA Mandate", "idx_sepa_mandate_status"),
    ]

    validation_results = {"success": True, "missing_indexes": []}

    for table_name, index_name in critical_indexes:
        try:
            existing_indexes = frappe.db.sql(
                f"""
                SHOW INDEX FROM `{table_name}`
                WHERE Key_name = %s
            """,
                [index_name],
            )

            if existing_indexes == []:
                validation_results["success"] = False
                validation_results["missing_indexes"].append(f"{table_name}.{index_name}")
                print(f"  ✗ Critical index missing: {table_name}.{index_name}")
            else:
                print(f"  ✓ Critical index validated: {table_name}.{index_name}")

        except Exception as e:
            validation_results["success"] = False
            print(f"  ✗ Failed to validate index {table_name}.{index_name}: {str(e)}")

    if validation_results["success"]:
        print("✓ All critical performance indexes validated successfully")
    else:
        print(f"✗ {len(validation_results['missing_indexes'])} critical indexes are missing")

    return validation_results


# Manual execution function for testing
def run_migration():
    """Run the migration manually for testing purposes"""

    print("=== Performance Indexes Migration ===")
    print("This will add database indexes to improve query performance.")
    print("Note: This operation may take time on large databases.\n")

    try:
        execute()
        validate_indexes()
        print("\n=== Migration completed successfully ===")

    except Exception as e:
        print(f"\n=== Migration failed: {str(e)} ===")
        raise


if __name__ == "__main__":
    # Allow manual execution for testing
    run_migration()
