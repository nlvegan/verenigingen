"""
Unit tests for volunteer statistics utilities

Tests the shared volunteer statistics module to ensure consistent
expense calculations across the volunteer expenses and dashboard pages.
"""

import unittest
from unittest.mock import patch, MagicMock
import frappe
from frappe.utils import today, add_months
from verenigingen.utils.volunteer_statistics import (
    get_volunteer_expense_statistics,
    get_volunteer_expense_summary,
    _map_erpnext_status_to_volunteer_status
)


class TestVolunteerStatistics(unittest.TestCase):
    """Test cases for volunteer statistics utilities"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.volunteer_name = "Test Volunteer"
        self.employee_id = "HR-EMP-00001"
        
    @patch('frappe.get_doc')
    @patch('frappe.get_all')  
    def test_get_volunteer_expense_statistics_with_employee(self, mock_get_all, mock_get_doc):
        """Test expense statistics calculation with ERPNext employee"""
        
        # Mock volunteer document with employee_id
        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = self.employee_id
        mock_get_doc.return_value = mock_volunteer
        
        # Mock expense claims data
        mock_expense_claims = [
            {
                "name": "EXP-001", 
                "total_claimed_amount": 100.0,
                "total_sanctioned_amount": 100.0,
                "status": "Draft",
                "approval_status": "Draft"
            },
            {
                "name": "EXP-002",
                "total_claimed_amount": 50.0, 
                "total_sanctioned_amount": 50.0,
                "status": "Paid",
                "approval_status": "Approved"
            },
            {
                "name": "EXP-003",
                "total_claimed_amount": 75.0,
                "total_sanctioned_amount": 75.0, 
                "status": "Unpaid",
                "approval_status": "Approved"
            }
        ]
        
        # Set up mock returns - first call for expense claims, second for volunteer expenses
        mock_get_all.side_effect = [mock_expense_claims, []]
        
        with patch('frappe.logger') as mock_logger:
            result = get_volunteer_expense_statistics(self.volunteer_name)
        
        # Verify calculations
        self.assertEqual(result["total_submitted"], 225.0)  # 100 + 50 + 75
        self.assertEqual(result["total_approved"], 125.0)   # 50 + 75 (Paid + Approved)
        self.assertEqual(result["pending_count"], 1)        # 1 Draft
        self.assertEqual(result["approved_count"], 2)       # 1 Paid + 1 Approved
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(result["pending_amount"], 100.0)   # 225 - 125
        
    @patch('frappe.get_doc')
    @patch('frappe.get_all')
    def test_get_volunteer_expense_statistics_no_employee(self, mock_get_all, mock_get_doc):
        """Test expense statistics with volunteer expenses only (no ERPNext employee)"""
        
        # Mock volunteer document without employee_id
        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = None
        mock_get_doc.return_value = mock_volunteer
        
        # Mock volunteer expense data
        mock_volunteer_expenses = [
            {"name": "VE-001", "amount": 30.0, "status": "Approved"},
            {"name": "VE-002", "amount": 20.0, "status": "Submitted"}
        ]
        
        mock_get_all.return_value = mock_volunteer_expenses
        
        with patch('frappe.logger') as mock_logger:
            result = get_volunteer_expense_statistics(self.volunteer_name)
        
        # Verify calculations
        self.assertEqual(result["total_submitted"], 50.0)   # 30 + 20
        self.assertEqual(result["total_approved"], 30.0)    # 30 (Approved)
        self.assertEqual(result["pending_count"], 1)        # 1 Submitted
        self.assertEqual(result["approved_count"], 1)       # 1 Approved
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["pending_amount"], 20.0)    # 50 - 30
        
    def test_get_volunteer_expense_summary(self):
        """Test expense summary adds recent_count field"""
        
        with patch('verenigingen.utils.volunteer_statistics.get_volunteer_expense_statistics') as mock_stats:
            with patch('frappe.get_doc') as mock_get_doc:
                with patch('frappe.db.count') as mock_count:
                    
                    # Mock the base statistics
                    mock_stats.return_value = {
                        "total_submitted": 100.0,
                        "total_approved": 50.0,
                        "pending_count": 2,
                        "approved_count": 1,
                        "total_count": 3,
                        "pending_amount": 50.0
                    }
                    
                    # Mock volunteer with employee_id
                    mock_volunteer = MagicMock()
                    mock_volunteer.employee_id = self.employee_id
                    mock_get_doc.return_value = mock_volunteer
                    
                    # Mock recent counts
                    mock_count.side_effect = [2, 1]  # 2 ERPNext recent, 1 Volunteer recent
                    
                    result = get_volunteer_expense_summary(self.volunteer_name)
                    
                    # Verify it has all base stats plus recent_count
                    self.assertEqual(result["total_submitted"], 100.0)
                    self.assertEqual(result["recent_count"], 3)  # 2 + 1
    
    def test_map_erpnext_status_to_volunteer_status(self):
        """Test ERPNext status mapping function"""
        
        # Test Draft status
        result = _map_erpnext_status_to_volunteer_status("Draft", "Draft")
        self.assertEqual(result, "Awaiting Approval")
        
        # Test Submitted with Approved
        result = _map_erpnext_status_to_volunteer_status("Submitted", "Approved") 
        self.assertEqual(result, "Approved")
        
        # Test Submitted with Rejected
        result = _map_erpnext_status_to_volunteer_status("Submitted", "Rejected")
        self.assertEqual(result, "Rejected")
        
        # Test Submitted without approval status
        result = _map_erpnext_status_to_volunteer_status("Submitted", "Draft")
        self.assertEqual(result, "Submitted")
        
        # Test Unpaid with Approved
        result = _map_erpnext_status_to_volunteer_status("Unpaid", "Approved")
        self.assertEqual(result, "Approved")
        
        # Test Paid status
        result = _map_erpnext_status_to_volunteer_status("Paid", "Approved")
        self.assertEqual(result, "Reimbursed")
        
        # Test Cancelled status
        result = _map_erpnext_status_to_volunteer_status("Cancelled", "Draft")
        self.assertEqual(result, "Rejected")
        
        # Test unknown status (fallback)
        result = _map_erpnext_status_to_volunteer_status("Unknown", "Draft")
        self.assertEqual(result, "Submitted")
        
    @patch('frappe.get_doc')
    @patch('frappe.get_all')
    @patch('frappe.log_error')
    def test_error_handling(self, mock_log_error, mock_get_all, mock_get_doc):
        """Test error handling returns safe defaults"""
        
        # Mock an exception during processing
        mock_get_doc.side_effect = Exception("Database error")
        
        result = get_volunteer_expense_statistics(self.volunteer_name)
        
        # Should return safe defaults
        self.assertEqual(result["total_submitted"], 0)
        self.assertEqual(result["total_approved"], 0) 
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["approved_count"], 0)
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["pending_amount"], 0)
        
        # Should have logged the error
        mock_log_error.assert_called_once()
        
    @patch('frappe.get_doc')
    @patch('frappe.get_all')
    def test_months_back_parameter(self, mock_get_all, mock_get_doc):
        """Test months_back parameter affects date filtering"""
        
        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = self.employee_id
        mock_get_doc.return_value = mock_volunteer
        
        mock_get_all.side_effect = [[], []]  # Empty results
        
        with patch('frappe.utils.add_months') as mock_add_months:
            # Test default 12 months
            get_volunteer_expense_statistics(self.volunteer_name)
            mock_add_months.assert_called_with(today(), -12)
            
            # Test custom months
            get_volunteer_expense_statistics(self.volunteer_name, months_back=6)
            mock_add_months.assert_called_with(today(), -6)


if __name__ == '__main__':
    unittest.main()