import frappe


def test_modules():
    """Simple test for modules"""
    try:
        from verenigingen.e_boekhouden.utils.consolidated.account_manager import EBoekhoudenAccountManager
        from verenigingen.e_boekhouden.utils.consolidated.party_manager import EBoekhoudenPartyManager
        from verenigingen.e_boekhouden.utils.security_helper import has_migration_permission

        print("✓ All modules import successfully")

        # Test security
        print(f"✓ Permission check works: {has_migration_permission('account_creation')}")

        # Test party manager
        party_mgr = EBoekhoudenPartyManager()
        print("✓ Party manager initializes")

        # Test account manager
        account_mgr = EBoekhoudenAccountManager("TEST")
        print("✓ Account manager initializes")

        # Test smart account type detection
        result = account_mgr._get_smart_account_type({"code": "1300", "description": "Debiteuren"})
        print(f"✓ Smart account detection: {result}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False
