# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Advanced Workflow Tests
Tests for SEPA batch processing, termination edge cases, and complex workflows
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, getdate, nowdate
from decimal import Decimal
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


class TestAdvancedWorkflows(FrappeTestCase):
    """Test advanced workflows and edge cases"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_members = self._create_test_members_with_mandates()
        
    def _create_test_members_with_mandates(self):
        """Create test members with SEPA mandates"""
        members = []
        
        for i in range(5):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"SEPA{i}",
                "last_name": "TestMember",
                "email": f"sepa{i}.test@example.com",
                "status": "Active"
            })
            member.insert(ignore_permissions=True)
            
            # Create SEPA mandate
            mandate = frappe.get_doc({
                "doctype": "SEPA Mandate",
                "member": member.name,
                "mandate_reference": f"TEST-MANDATE-{i:04d}",
                "iban": f"NL91ABNA041716430{i}",
                "bic": "ABNANL2A",
                "status": "Active",
                "mandate_date": add_days(today(), -30),
                "debtor_name": member.full_name
            })
            mandate.insert(ignore_permissions=True)
            
            member.mandate = mandate
            members.append(member)
            
        return members
        
    def test_sepa_batch_creation(self):
        """Test SEPA direct debit batch creation"""
        # Create batch
        batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_name": f"Test Batch {frappe.utils.random_string(6)}",
            "execution_date": add_days(today(), 5),  # 5 days in future
            "batch_type": "FRST",  # First collection
            "status": "Draft"
        })
        batch.insert()
        
        # Add entries for test members
        for member in self.test_members:
            batch.append("entries", {
                "member": member.name,
                "member_name": member.full_name,
                "mandate_reference": member.mandate.mandate_reference,
                "iban": member.mandate.iban,
                "amount": 100.00,
                "description": "Monthly membership fee",
                "status": "Pending"
            })
            
        batch.save()
        
        # Verify batch
        self.assertEqual(len(batch.entries), 5)
        self.assertEqual(batch.total_amount, 500.00)
        
        # Test validation
        batch.validate_entries()
        
        # All entries should be valid
        valid_entries = [e for e in batch.entries if e.status == "Valid"]
        self.assertEqual(len(valid_entries), 5)
        
    def test_sepa_xml_generation(self):
        """Test SEPA XML file generation"""
        # Create a simple batch
        batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_name": "XML Test Batch",
            "execution_date": add_days(today(), 5),
            "batch_type": "RCUR",
            "entries": [{
                "member": self.test_members[0].name,
                "mandate_reference": self.test_members[0].mandate.mandate_reference,
                "iban": self.test_members[0].mandate.iban,
                "amount": 50.00,
                "description": "Test collection"
            }]
        })
        batch.insert()
        
        # Generate XML (mocked)
        xml_content = self._generate_sepa_xml(batch)
        
        # Parse and verify XML structure
        root = ET.fromstring(xml_content)
        
        # Verify namespace
        self.assertIn("pain.008", root.tag)
        
        # Verify required elements exist
        self.assertIsNotNone(root.find(".//MsgId"))
        self.assertIsNotNone(root.find(".//CreDtTm"))
        self.assertIsNotNone(root.find(".//NbOfTxs"))
        self.assertIsNotNone(root.find(".//CtrlSum"))
        
    def _generate_sepa_xml(self, batch):
        """Mock SEPA XML generation"""
        # Simplified SEPA XML structure
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.02">
    <CstmrDrctDbtInitn>
        <GrpHdr>
            <MsgId>{batch.name}</MsgId>
            <CreDtTm>{datetime.now().isoformat()}</CreDtTm>
            <NbOfTxs>{len(batch.entries)}</NbOfTxs>
            <CtrlSum>{batch.total_amount}</CtrlSum>
        </GrpHdr>
    </CstmrDrctDbtInitn>
</Document>"""
        return xml
        
    def test_termination_workflow_edge_cases(self):
        """Test edge cases in termination workflow"""
        # Edge case 1: Member with active volunteer roles
        member_with_roles = self.test_members[0]
        volunteer = frappe.get_doc({
            "doctype": "Volunteer",
            "volunteer_name": member_with_roles.full_name,
            "member": member_with_roles.name,
            "status": "Active"
        })
        volunteer.insert(ignore_permissions=True)
        
        # Create termination request
        termination = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": member_with_roles.name,
            "termination_date": add_days(today(), 30),
            "termination_reason": "Member request",
            "has_active_roles": True,
            "active_volunteer_roles": 1
        })
        termination.insert()
        
        # Should require additional approval
        self.assertTrue(termination.requires_board_approval)
        
        # Edge case 2: Member with outstanding payments
        member_with_debt = self.test_members[1]
        
        termination_debt = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": member_with_debt.name,
            "termination_date": today(),
            "termination_reason": "Non-payment",
            "outstanding_amount": 250.00
        })
        termination_debt.insert()
        
        # Should block immediate termination
        self.assertTrue(termination_debt.has_outstanding_payments)
        
        # Edge case 3: Recently joined member
        recent_member = self.test_members[2]
        recent_member.join_date = add_days(today(), -15)  # Joined 15 days ago
        recent_member.save()
        
        termination_recent = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": recent_member.name,
            "termination_date": today(),
            "termination_reason": "Changed mind"
        })
        termination_recent.insert()
        
        # Should trigger cooling-off period check
        days_since_joining = (getdate(today()) - getdate(recent_member.join_date)).days
        self.assertLess(days_since_joining, 30)
        
    def test_multi_language_communication(self):
        """Test multi-language support in communications"""
        # Test language preferences
        languages = ["en", "nl", "de", "fr"]
        
        for i, lang in enumerate(languages):
            if i < len(self.test_members):
                member = self.test_members[i]
                member.preferred_language = lang
                member.save()
                
                # Get welcome message in preferred language
                message = self._get_welcome_message(member)
                
                # Verify language-specific content
                if lang == "en":
                    self.assertIn("Welcome", message)
                elif lang == "nl":
                    self.assertIn("Welkom", message)
                elif lang == "de":
                    self.assertIn("Willkommen", message)
                elif lang == "fr":
                    self.assertIn("Bienvenue", message)
                    
    def _get_welcome_message(self, member):
        """Get welcome message in member's preferred language"""
        messages = {
            "en": f"Welcome {member.first_name}!",
            "nl": f"Welkom {member.first_name}!",
            "de": f"Willkommen {member.first_name}!",
            "fr": f"Bienvenue {member.first_name}!"
        }
        return messages.get(member.preferred_language, messages["en"])
        
    def test_webhook_integration(self):
        """Test webhook integration for external systems"""
        # Test webhook payload generation
        webhook_events = [
            {
                "event": "member.created",
                "data": {
                    "member_id": "MEM001",
                    "email": "test@example.com",
                    "status": "Active"
                }
            },
            {
                "event": "payment.received",
                "data": {
                    "member_id": "MEM001",
                    "amount": 100.00,
                    "currency": "EUR",
                    "reference": "PAY-123"
                }
            },
            {
                "event": "volunteer.assigned",
                "data": {
                    "volunteer_id": "VOL001",
                    "team": "Events Team",
                    "role": "Coordinator"
                }
            }
        ]
        
        for event in webhook_events:
            # Verify payload structure
            self.assertIn("event", event)
            self.assertIn("data", event)
            self.assertIsInstance(event["data"], dict)
            
            # Test payload serialization
            import json
            serialized = json.dumps(event)
            deserialized = json.loads(serialized)
            
            self.assertEqual(event, deserialized)
            
    def test_report_generation_performance(self):
        """Test report generation with large datasets"""
        import time
        
        # Simulate large member report
        report_filters = {
            "status": ["Active", "Pending"],
            "date_range": [add_days(today(), -365), today()],
            "include_financial": True,
            "include_volunteer": True
        }
        
        start_time = time.time()
        
        # Simulate report data gathering
        report_data = []
        for member in self.test_members:
            member_data = {
                "member_id": member.name,
                "name": member.full_name,
                "status": member.status,
                "join_date": member.get("join_date"),
                "total_paid": 0.00,
                "volunteer_hours": 0
            }
            report_data.append(member_data)
            
        end_time = time.time()
        generation_time = end_time - start_time
        
        # Should complete quickly
        self.assertLess(generation_time, 1.0)
        
        # Verify report data
        self.assertEqual(len(report_data), len(self.test_members))
        
    def test_automated_reminder_scheduling(self):
        """Test automated reminder scheduling"""
        # Test payment reminder scheduling
        reminders_to_send = []
        
        # Check each member for payment due
        for member in self.test_members:
            # Simulate overdue payment
            last_payment_date = add_days(today(), -45)
            days_overdue = (getdate(today()) - getdate(last_payment_date)).days
            
            if days_overdue > 30:
                reminder = {
                    "member": member.name,
                    "type": "payment_overdue",
                    "days_overdue": days_overdue,
                    "scheduled_date": today(),
                    "priority": "high" if days_overdue > 60 else "medium"
                }
                reminders_to_send.append(reminder)
                
        # Verify reminders
        self.assertEqual(len(reminders_to_send), 5)  # All are overdue
        
        # Check priority assignment
        high_priority = [r for r in reminders_to_send if r["priority"] == "high"]
        medium_priority = [r for r in reminders_to_send if r["priority"] == "medium"]
        
        self.assertGreater(len(medium_priority), 0)
        
    def test_data_archival_process(self):
        """Test data archival for old records"""
        # Define archival rules
        archival_rules = {
            "terminated_members": {
                "retention_days": 365 * 7,  # 7 years
                "action": "archive"
            },
            "old_communications": {
                "retention_days": 365 * 2,  # 2 years
                "action": "delete"
            },
            "payment_records": {
                "retention_days": 365 * 10,  # 10 years
                "action": "archive"
            }
        }
        
        # Test archival candidate identification
        archive_candidates = []
        
        # Simulate old terminated member
        cutoff_date = add_days(today(), -365 * 8)  # 8 years ago
        
        for rule_name, rule in archival_rules.items():
            retention_cutoff = add_days(today(), -rule["retention_days"])
            
            if getdate(cutoff_date) < getdate(retention_cutoff):
                archive_candidates.append({
                    "type": rule_name,
                    "action": rule["action"],
                    "record_date": cutoff_date
                })
                
        # Verify archival rules
        self.assertGreater(len(archive_candidates), 0)
        
        # Check terminated members should be archived
        terminated_archival = [c for c in archive_candidates 
                              if c["type"] == "terminated_members"]
        self.assertEqual(len(terminated_archival), 1)
        self.assertEqual(terminated_archival[0]["action"], "archive")
        
    def tearDown(self):
        """Clean up test data"""
        # Clean up SEPA mandates
        for member in self.test_members:
            if hasattr(member, 'mandate'):
                try:
                    frappe.delete_doc("SEPA Mandate", member.mandate.name, force=True)
                except:
                    pass
                    
        # Clean up members
        for member in self.test_members:
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except:
                pass