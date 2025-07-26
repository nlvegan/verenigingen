#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Install SEPA Audit Log DocType manually
"""

import json
import os

import frappe


@frappe.whitelist()
def install_sepa_audit_log():
    """Install SEPA Audit Log DocType manually"""
    try:
        # Check if already exists
        if frappe.db.exists("DocType", "SEPA Audit Log"):
            return {"status": "success", "message": "SEPA Audit Log already exists"}

        # Read the JSON file
        json_path = os.path.join(
            frappe.get_app_path("verenigingen"), "doctype", "sepa_audit_log", "sepa_audit_log.json"
        )

        with open(json_path, "r") as f:
            doctype_data = json.load(f)

        # Create the DocType document
        doctype_doc = frappe.get_doc(doctype_data)
        doctype_doc.insert(ignore_permissions=True)

        # Commit the transaction
        frappe.db.commit()

        return {
            "status": "success",
            "message": f"SEPA Audit Log DocType created successfully: {doctype_doc.name}",
        }

    except Exception as e:
        frappe.log_error(f"Failed to install SEPA Audit Log: {str(e)}")
        return {"status": "error", "message": f"Installation failed: {str(e)}"}


@frappe.whitelist()
def create_sepa_audit_table():
    """Create the SEPA Audit Log database table"""
    try:
        if not frappe.db.exists("DocType", "SEPA Audit Log"):
            return {"status": "error", "message": "DocType SEPA Audit Log does not exist"}

        # Get the DocType
        doctype = frappe.get_doc("DocType", "SEPA Audit Log")

        # Create the table
        frappe.db.create_table("SEPA Audit Log", doctype.as_dict())
        frappe.db.commit()

        return {"status": "success", "message": "SEPA Audit Log table created successfully"}

    except Exception as e:
        frappe.log_error(f"Failed to create SEPA Audit Log table: {str(e)}")
        return {"status": "error", "message": f"Table creation failed: {str(e)}"}
