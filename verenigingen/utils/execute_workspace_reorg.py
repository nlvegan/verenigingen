#!/usr/bin/env python3
"""Execute workspace reorganization"""

import frappe


@frappe.whitelist()
def fix_content_sync():
    """Fix content synchronization after reorganization"""
    from verenigingen.utils.workspace_content_fixer import fix_workspace_content

    print("🔧 Fixing content synchronization for Verenigingen workspace...")
    result = fix_workspace_content("Verenigingen", dry_run=False)

    if result:
        print("✅ Content synchronization fixed successfully!")
    else:
        print("ℹ️  No content fixes needed")

    return result


@frappe.whitelist()
def check_payments_workspace():
    """Check the reports in Verenigingen Payments workspace"""
    from verenigingen.utils.workspace_reports_organizer import get_reports_structure

    result = get_reports_structure("Verenigingen Payments")

    print("📊 VERENIGINGEN PAYMENTS WORKSPACE:")
    print(f"Total reports: {result['total_reports']}")
    print(f"Financial reports: {len(result['categorized']['financial_reports'])}")

    if result["categorized"]["financial_reports"]:
        print("\n💰 Financial Reports:")
        for report in result["categorized"]["financial_reports"]:
            print(f"  - {report['label']}")

    return result


@frappe.whitelist()
def analyze_card_break_structure():
    """Analyze the current Card Break hierarchy structure"""

    # Get all Card Breaks in Verenigingen workspace
    card_breaks = frappe.db.sql(
        """
        SELECT label, idx, link_count, parent
        FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen' AND type = 'Card Break'
        ORDER BY idx
    """,
        as_dict=True,
    )

    print("📊 CURRENT CARD BREAK STRUCTURE:")
    print("=" * 50)
    for i, cb in enumerate(card_breaks, 1):
        print(f"{i:2d}. {cb.label} (idx: {cb.idx}, link_count: {cb.link_count})")

    # Check report-related Card Breaks
    reports_breaks = [cb for cb in card_breaks if "Report" in cb.label]
    print(f"\nReport-related Card Breaks: {len(reports_breaks)}")
    for rb in reports_breaks:
        print(f"  - {rb.label} (idx: {rb.idx})")

    # Check if we have the right hierarchy - should be Reports parent with sub-sections
    reports_parent = None
    for cb in card_breaks:
        if cb.label == "Reports":
            reports_parent = cb
            break

    print("\nHierarchy Analysis:")
    if reports_parent:
        print(f'✅ Found "Reports" parent section at idx {reports_parent.idx}')
    else:
        print('❌ Missing "Reports" parent section - this could be the issue!')
        print('   Current structure has report subsections but no parent "Reports" section')

    return {
        "card_breaks": card_breaks,
        "reports_breaks": reports_breaks,
        "has_reports_parent": reports_parent is not None,
        "reports_parent": reports_parent,
    }


@frappe.whitelist()
def fix_reports_hierarchy():
    """Fix the reports hierarchy by adding parent 'Reports' Card Break"""

    print("🔧 Fixing reports hierarchy structure...")

    # Find the first report-related Card Break to determine where to insert the parent
    first_report_break = frappe.db.sql(
        """
        SELECT name, idx FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        AND type = 'Card Break'
        AND label LIKE '%Report%'
        ORDER BY idx
        LIMIT 1
    """,
        as_dict=True,
    )

    if not first_report_break:
        print("❌ No report Card Breaks found")
        return False

    insert_idx = first_report_break[0].idx
    print(f"📍 Will insert parent 'Reports' Card Break at idx {insert_idx}")

    # Shift all existing report sections down to make room for parent
    frappe.db.sql(
        """
        SELECT name, idx FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        AND type = 'Card Break'
        AND label LIKE '%Report%'
        ORDER BY idx
    """,
        as_dict=True,
    )

    # Also need to shift any links that come after the first report break
    links_to_shift = frappe.db.sql(
        """
        SELECT name, idx FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        AND idx >= %s
        ORDER BY idx
    """,
        insert_idx,
        as_dict=True,
    )

    print(f"📊 Will shift {len(links_to_shift)} items down by 1 index")

    # Shift everything down by 1
    for item in reversed(links_to_shift):  # Reverse to avoid conflicts
        frappe.db.sql(
            """
            UPDATE `tabWorkspace Link`
            SET idx = %s
            WHERE name = %s
        """,
            (item.idx + 1, item.name),
        )

    # Create the parent "Reports" Card Break
    total_report_links = frappe.db.sql(
        """
        SELECT COUNT(*) as count FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        AND type = 'Link'
        AND link_type = 'Report'
    """,
        as_dict=True,
    )[0].count

    reports_parent_doc = frappe.get_doc(
        {
            "doctype": "Workspace Link",
            "parent": "Verenigingen",
            "parenttype": "Workspace",
            "parentfield": "links",
            "type": "Card Break",
            "label": "Reports",
            "link_count": total_report_links,
            "idx": insert_idx,
        }
    )
    reports_parent_doc.insert(ignore_permissions=True)

    frappe.db.commit()
    print(f"✅ Created parent 'Reports' Card Break at idx {insert_idx}")
    print(f"✅ Shifted {len(links_to_shift)} items to accommodate new parent")
    print("✅ Reports hierarchy fixed successfully!")

    return True


@frappe.whitelist()
def debug_reports_rendering():
    """Debug why reports section isn't rendering properly"""

    print("🔍 DEBUGGING REPORTS SECTION RENDERING")
    print("=" * 50)

    # Get detailed structure around Reports section
    all_links = frappe.db.sql(
        """
        SELECT name, label, type, link_type, link_to, idx, hidden
        FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        AND idx BETWEEN 45 AND 70
        ORDER BY idx
    """,
        as_dict=True,
    )

    print("📊 DETAILED STRUCTURE AROUND REPORTS:")
    for link in all_links:
        icon = "📂" if link.type == "Card Break" else "📄"
        hidden_status = " (HIDDEN)" if link.hidden else ""
        print(f"idx {link.idx:2d}: {icon} {link.label}{hidden_status}")
        if link.type == "Link":
            print(f"        → {link.link_type}: {link.link_to}")

    # Check if there are any issues with the report links themselves
    broken_report_links = []
    for link in all_links:
        if link.type == "Link" and link.link_type == "Report":
            if not frappe.db.exists("Report", link.link_to):
                broken_report_links.append(link.label)

    if broken_report_links:
        print(f"\\n❌ BROKEN REPORT LINKS: {broken_report_links}")
    else:
        print("\\n✅ All report links are valid")

    # Check the content field synchronization
    workspace = frappe.get_doc("Workspace", "Verenigingen")
    if workspace.content:
        import json

        try:
            content_data = json.loads(workspace.content)
            reports_cards = [
                item
                for item in content_data
                if item.get("type") == "card"
                and "report" in item.get("data", {}).get("card_name", "").lower()
            ]
            print(f"\\n📄 REPORTS CARDS IN CONTENT FIELD: {len(reports_cards)}")
            for card in reports_cards:
                card_name = card.get("data", {}).get("card_name", "Unknown")
                print(f"   - {card_name}")
        except:
            print("\\n❌ Error parsing content field JSON")

    return {
        "links_around_reports": all_links,
        "broken_links": broken_report_links,
        "total_links": len(all_links),
    }


@frappe.whitelist()
def fix_index_conflicts():
    """Fix index conflicts in workspace links"""

    print("🔧 Fixing index conflicts in workspace links...")

    # Get all links ordered by current idx
    all_links = frappe.db.sql(
        """
        SELECT name, label, type, idx
        FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        ORDER BY idx, name
    """,
        as_dict=True,
    )

    print(f"📊 Found {len(all_links)} total workspace links")

    # Find conflicts
    seen_indices = {}
    conflicts = []

    for link in all_links:
        if link.idx in seen_indices:
            conflicts.append({"idx": link.idx, "existing": seen_indices[link.idx], "conflicting": link})
        else:
            seen_indices[link.idx] = link

    print(f"⚠️  Found {len(conflicts)} index conflicts")
    for conflict in conflicts:
        print(
            f"   idx {conflict['idx']}: '{conflict['existing']['label']}' vs '{conflict['conflicting']['label']}'"
        )

    if conflicts:
        # Reassign indices sequentially
        print("🔧 Reassigning indices sequentially...")

        new_idx = 1
        for link in all_links:
            if link.idx != new_idx:
                frappe.db.sql(
                    """
                    UPDATE `tabWorkspace Link`
                    SET idx = %s
                    WHERE name = %s
                """,
                    (new_idx, link.name),
                )
                print(f"   Updated '{link.label}': {link.idx} → {new_idx}")
            new_idx += 1

        frappe.db.commit()
        print(f"✅ Fixed all index conflicts - items now numbered 1-{new_idx - 1}")
        return True
    else:
        print("✅ No index conflicts found")
        return False


@frappe.whitelist()
def execute_reorganization():
    """Execute the reorganization and copy operations"""

    from verenigingen.utils.workspace_reports_organizer import (
        copy_financial_section_to_payments_workspace,
        reorganize_reports_section,
    )

    results = {}

    try:
        # Step 1: Reorganize reports section
        print("🔧 Step 1: Reorganizing reports section...")
        result1 = reorganize_reports_section("Verenigingen", dry_run=False)
        results["reorganization"] = result1

        # Step 2: Copy financial section to payments workspace
        print("🔧 Step 2: Copying financial section to payments workspace...")
        result2 = copy_financial_section_to_payments_workspace(dry_run=False)
        results["copy_financial"] = result2

        print("✅ Both operations completed successfully!")

    except Exception as e:
        print(f"❌ Error during operations: {str(e)}")
        results["error"] = str(e)

    return results
