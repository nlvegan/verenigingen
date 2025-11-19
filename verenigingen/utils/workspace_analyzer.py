#!/usr/bin/env python3
"""
Workspace Content Analyzer
Analyzes workspace content vs database structure mismatches
"""

import json

import frappe


def analyze_workspace(workspace_name):
    """Compare content field cards with Card Break structure"""

    workspace = frappe.get_doc("Workspace", workspace_name)

    # Parse content field
    content = json.loads(workspace.content)
    content_cards = [
        item.get("data", {}).get("card_name")
        for item in content
        if item.get("type") == "card" and item.get("data", {}).get("card_name")
    ]

    # Get Card Break labels
    card_breaks = frappe.db.sql(
        """
        SELECT label FROM `tabWorkspace Link`
        WHERE parent = %s AND type = 'Card Break'
        ORDER BY label
    """,
        workspace_name,
        as_dict=True,
    )

    card_break_labels = [cb.label for cb in card_breaks]

    # Find mismatches
    content_only = set(content_cards) - set(card_break_labels)
    db_only = set(card_break_labels) - set(content_cards)
    matches = set(content_cards) & set(card_break_labels)

    return {
        "content_cards": content_cards,
        "card_breaks": card_break_labels,
        "content_only": list(content_only),
        "db_only": list(db_only),
        "matches": list(matches),
        "is_synchronized": len(content_only) == 0 and len(db_only) == 0,
        "total_links": frappe.db.count("Workspace Link", {"parent": workspace_name, "type": "Link"}),
        "total_card_breaks": len(card_break_labels),
    }


def print_analysis(workspace_name):
    """Print detailed analysis of workspace structure"""
    result = analyze_workspace(workspace_name)

    print(f"=== Workspace Analysis: {workspace_name} ===")
    print(f"Synchronized: {result['is_synchronized']}")
    print(f"Total Links: {result['total_links']}")
    print(f"Total Card Breaks: {result['total_card_breaks']}")
    print()

    if result["content_only"]:
        print("❌ Cards in content but no Card Break in database:")
        for card in result["content_only"]:
            print(f"  - {card}")
        print()

    if result["db_only"]:
        print("❌ Card Breaks in database but no content card:")
        for card in result["db_only"]:
            print(f"  - {card}")
        print()

    if result["matches"]:
        print("✅ Properly matched cards:")
        for card in result["matches"]:
            print(f"  - {card}")
        print()

    return result


def get_card_links(workspace_name, card_break_label):
    """Get all links under a specific Card Break"""

    # This is complex due to the sequential nature of workspace links
    # We need to find links that come after a Card Break but before the next Card Break

    links = frappe.db.sql(
        """
        WITH ordered_links AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY idx) as rn
            FROM `tabWorkspace Link`
            WHERE parent = %s
        ),
        card_break_positions AS (
            SELECT label, rn as card_break_rn
            FROM ordered_links
            WHERE type = 'Card Break' AND label = %s
        ),
        next_card_break AS (
            SELECT MIN(rn) as next_rn
            FROM ordered_links ol, card_break_positions cbp
            WHERE ol.type = 'Card Break' AND ol.rn > cbp.card_break_rn
        )
        SELECT ol.label, ol.link_to, ol.link_type
        FROM ordered_links ol, card_break_positions cbp
        LEFT JOIN next_card_break ncb ON 1=1
        WHERE ol.type = 'Link'
          AND ol.rn > cbp.card_break_rn
          AND (ncb.next_rn IS NULL OR ol.rn < ncb.next_rn)
        ORDER BY ol.rn
    """,
        (workspace_name, card_break_label),
        as_dict=True,
    )

    return links
