# -*- coding: utf-8 -*-
"""Submit a membership application through the real Guest endpoint, for approval tests.

One shared copy (it had been copy-pasted into the #1797 and #1860 approval test modules).
"""

import json

import frappe


def submit_application_as_guest(testcase, membership_type, **overrides):
    """Submit an application as Guest via `submit_application` and return the new Member name.

    The applicant gets a city and postal code that no chapter can match, so no chapter is
    SUGGESTED at submit: `suggest_chapter_for_member` also matches on the CITY, and CI shards carry
    shared chapters such as "Test Amsterdam Chapter" (an applicant from "Amsterdam" went red in CI,
    #1862). Pass `selected_chapter=` to choose one. The session is restored to Administrator and
    the Member is tracked for cleanup on `testcase`.
    """
    from verenigingen.api.membership_application import submit_application

    data = {
        "first_name": "Applicant",
        "last_name": f"Guest{frappe.generate_hash(length=6)}",
        "email": f"ga-{frappe.generate_hash(length=8)}@example.com",
        "birth_date": "1990-01-01",
        "address_line1": "1 Test Street",
        "city": f"Nergenshuizen-{frappe.generate_hash(length=6)}",
        "postal_code": "9999ZZ",
        "country": "Netherlands",
        "selected_membership_type": membership_type,
    }
    data.update({k: v for k, v in overrides.items() if v is not None})
    frappe.set_user("Guest")
    testcase.addCleanup(frappe.set_user, "Administrator")
    result = submit_application(**data)
    frappe.set_user("Administrator")
    testcase.assertTrue(result["success"], msg=json.dumps(result, default=str))
    member = result["data"]["member_record"]
    testcase.track_doc("Member", member)
    return member
