import frappe


def test_cleanup():
    """Test cleanup functionality"""
    # Get settings
    settings = frappe.get_single("E-Boekhouden Settings")
    company = settings.default_company

    print(f"Testing cleanup for company: {company}")

    # Check E-Boekhouden accounts before cleanup
    eb_accounts = frappe.get_all(
        "Account",
        filters={"company": company, "eboekhouden_grootboek_nummer": ["is", "set"]},
        fields=["name", "account_name", "is_group", "lft", "rgt"],
        order_by="lft",
    )

    print(f"\nBefore cleanup: {len(eb_accounts)} E-Boekhouden accounts")

    # Find group accounts with children
    group_accounts = [acc for acc in eb_accounts if acc.is_group]
    print(f"Group accounts: {len(group_accounts)}")

    for grp in group_accounts[:3]:
        # Count children
        children = frappe.get_all(
            "Account", filters={"lft": [">", grp.lft], "rgt": ["<", grp.rgt], "company": company}
        )
        print(f"  - {grp.account_name}: {len(children)} children")

    # Test the cleanup
    from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
        cleanup_chart_of_accounts,
    )

    try:
        result = cleanup_chart_of_accounts(company)
        print("\nCleanup completed successfully!")
        print(f"Result: {result}")
    except Exception as e:
        print(f"\nCleanup failed with error: {str(e)}")
        import traceback

        traceback.print_exc()

    # Check what's left
    remaining = frappe.get_all(
        "Account", filters={"company": company, "eboekhouden_grootboek_nummer": ["is", "set"]}
    )

    print(f"\nAfter cleanup: {len(remaining)} E-Boekhouden accounts remaining")

    return {"before": len(eb_accounts), "after": len(remaining), "deleted": len(eb_accounts) - len(remaining)}
