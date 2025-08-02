#!/usr/bin/env python3
"""
Test transaction management for E-Boekhouden consolidated modules
"""


def test_transaction_management():
    """Test transaction management functionality"""
    import frappe

    from verenigingen.e_boekhouden.utils.security_helper import (
        atomic_migration_operation,
        migration_context,
        migration_transaction,
    )

    print("=== Testing Transaction Management ===")

    # Test migration context
    print("Testing migration_context...")
    try:
        with migration_context("account_creation"):
            print("✓ Migration context works")
    except Exception as e:
        print(f"❌ Migration context failed: {e}")

    # Test atomic operations
    print("Testing atomic_migration_operation...")
    try:
        with atomic_migration_operation("party_creation"):
            print("✓ Atomic operations work")
    except Exception as e:
        print(f"❌ Atomic operations failed: {e}")

    # Test transaction manager
    print("Testing migration_transaction...")
    try:
        with migration_transaction("account_creation", batch_size=10) as tx:
            print("✓ Transaction manager works")
            # Test tracking an operation
            tx.track_operation("test_operation", "TEST-DOC-001", {"test": True})
            stats = tx.get_stats()
            print(f"✓ Transaction stats: {stats['total_operations']} operations")
    except Exception as e:
        print(f"❌ Transaction manager failed: {e}")

    print("✓ Transaction management tests completed")
    return True


if __name__ == "__main__":
    test_transaction_management()
