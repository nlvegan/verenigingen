#!/usr/bin/env python3
"""
Script to add chapter tracking fields to Member doctype
"""
import json


def add_chapter_tracking_fields():
    """Add chapter assignment tracking fields to Member doctype"""

    # Get the Member doctype
    doctype_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.json"
    )

    with open(doctype_path, "r") as f:
        member_doctype = json.load(f)

    # Find the index of primary_chapter in field_order
    field_order = member_doctype["field_order"]
    try:
        primary_chapter_index = field_order.index("primary_chapter")
    except ValueError:
        print("primary_chapter field not found in field_order")
        return False

    # New fields to add after primary_chapter
    new_field_names = [
        "chapter_assigned_date",
        "chapter_assigned_by",
        "previous_chapter",
        "chapter_change_reason",
    ]

    # Insert new field names in field_order after primary_chapter
    for i, field_name in enumerate(new_field_names):
        if field_name not in field_order:
            field_order.insert(primary_chapter_index + 1 + i, field_name)

    # New field definitions
    new_fields = [
        {
            "fieldname": "chapter_assigned_date",
            "fieldtype": "Datetime",
            "label": "Chapter Assigned Date",
            "read_only": 1,
            "description": "Date when member was assigned to current chapter",
        },
        {
            "fieldname": "chapter_assigned_by",
            "fieldtype": "Link",
            "label": "Chapter Assigned By",
            "options": "User",
            "read_only": 1,
            "description": "User who assigned member to current chapter",
        },
        {
            "fieldname": "previous_chapter",
            "fieldtype": "Link",
            "label": "Previous Chapter",
            "options": "Chapter",
            "read_only": 1,
            "description": "Member's previous chapter before current assignment",
        },
        {
            "fieldname": "chapter_change_reason",
            "fieldtype": "Small Text",
            "label": "Chapter Change Reason",
            "description": "Reason for chapter assignment/change",
        },
    ]

    # Find existing fields and add new ones if they don't exist
    existing_fieldnames = [field.get("fieldname") for field in member_doctype["fields"]]

    for field in new_fields:
        if field["fieldname"] not in existing_fieldnames:
            # Find the primary_chapter field in fields array
            primary_chapter_field_index = None
            for i, existing_field in enumerate(member_doctype["fields"]):
                if existing_field.get("fieldname") == "primary_chapter":
                    primary_chapter_field_index = i
                    break

            if primary_chapter_field_index is not None:
                # Insert after primary_chapter field
                member_doctype["fields"].insert(primary_chapter_field_index + 1, field)
                primary_chapter_field_index += 1  # Update index for next insertion
            else:
                # Fallback: append to end
                member_doctype["fields"].append(field)

    # Update modified timestamp
    from datetime import datetime

    member_doctype["modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    # Write back to file
    with open(doctype_path, "w") as f:
        json.dump(member_doctype, f, indent=1)

    print("Chapter tracking fields added successfully!")
    print("Added fields:")
    for field in new_fields:
        print(f"  - {field['fieldname']}: {field['label']}")

    return True


if __name__ == "__main__":
    add_chapter_tracking_fields()
