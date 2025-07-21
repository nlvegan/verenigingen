#!/usr/bin/env python3
"""
Email Template Validation Test Suite

Tests all email templates for proper variable syntax, missing variables,
and consistent formatting. Can be run as part of the test suite or pre-commit checks.
"""

import json
import os
import re
from unittest.mock import Mock

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestEmailTemplateValidation(VereningingenTestCase):
    """Comprehensive email template validation test suite"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures and mock data"""
        super().setUpClass()
        
        # Create mock data for template testing
        cls.mock_data = {
            "member": Mock(
                name="TEST-MEMBER-001",
                full_name="John Test Doe",
                first_name="John",
                last_name="Doe",
                email="john.test@example.com",
                application_id="APP-2025-001"
            ),
            "doc": Mock(
                name="TEST-DOC-001",
                termination_type="Voluntary",
                reason_for_termination="Personal reasons"
            ),
            "invoice": Mock(
                name="SINV-2025-001",
                grand_total=25.00,
                currency="EUR",
                due_date=today()
            ),
            "application_id": "APP-2025-001",
            "member_name": "John Test Doe",
            "company": "Test Organization",
            "base_url": "https://test.example.com",
            "overdue_count": 5,
            "termination_date": today()
        }

    def test_email_fixture_templates_syntax(self):
        """Test email templates from fixtures for proper Jinja2 syntax"""
        fixture_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/email_template.json"
        
        if not os.path.exists(fixture_path):
            self.skipTest("Email template fixtures not found")
        
        with open(fixture_path, 'r') as f:
            templates = json.load(f)
        
        issues = []
        
        for template in templates:
            template_name = template.get('name', 'Unknown')
            subject = template.get('subject', '')
            response = template.get('response', '')
            
            # Test 1: Check for proper Jinja2 syntax in subject
            subject_issues = self._validate_jinja2_syntax(subject, f"{template_name} subject")
            issues.extend(subject_issues)
            
            # Test 2: Check for proper Jinja2 syntax in response
            response_issues = self._validate_jinja2_syntax(response, f"{template_name} response")
            issues.extend(response_issues)
            
            # Test 3: Check for common variable naming consistency
            consistency_issues = self._check_variable_consistency(subject, response, template_name)
            issues.extend(consistency_issues)
        
        if issues:
            self.fail(f"Email template fixture issues found:\n" + "\n".join(issues))

    def test_python_email_templates_syntax(self):
        """Test email templates in Python code for proper f-string syntax"""
        issues = []
        
        # Scan Python files for email template issues
        app_directory = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen"
        
        for root, dirs, files in os.walk(app_directory):
            # Skip test directories and cache
            if any(skip in root for skip in ['__pycache__', '.git', 'node_modules', '/tests/']):
                continue
                
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    relative_path = file_path.replace(app_directory, "")
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                        file_issues = self._scan_python_email_syntax(content, relative_path)
                        issues.extend(file_issues)
                        
                    except Exception as e:
                        # Log but don't fail on unreadable files
                        continue
        
        if issues:
            self.fail(f"Python email template issues found:\n" + "\n".join(issues))

    def test_email_template_variable_rendering(self):
        """Test that email templates render properly with mock data"""
        issues = []
        
        # Test common email templates that exist in the system
        test_templates = [
            {
                "subject": "Membership Application Received - ID: {application_id}",
                "expected_vars": ["application_id"],
                "test_name": "Application Confirmation"
            },
            {
                "subject": "New Application: {application_id} - {member.full_name}",
                "expected_vars": ["application_id", "member.full_name"],
                "test_name": "Reviewer Notification"
            },
            {
                "subject": "Membership Approved - Payment Required",
                "expected_vars": [],
                "test_name": "Approval Notification"
            }
        ]
        
        for template in test_templates:
            try:
                # Test f-string style formatting
                if template["expected_vars"]:
                    # Create test data based on expected variables
                    test_data = {}
                    for var in template["expected_vars"]:
                        if "." in var:
                            # Handle nested attributes like member.full_name
                            parts = var.split(".")
                            if parts[0] not in test_data:
                                test_data[parts[0]] = self.mock_data.get(parts[0], Mock())
                        else:
                            test_data[var] = self.mock_data.get(var, f"TEST_{var.upper()}")
                    
                    # Test formatting
                    formatted = template["subject"].format(**test_data)
                    
                    # Check that no variables remain unparsed
                    if "{" in formatted and "}" in formatted:
                        issues.append(f"{template['test_name']}: Variables not properly parsed in '{formatted}'")
                        
                else:
                    # Template with no variables should render as-is
                    formatted = template["subject"]
                
            except Exception as e:
                issues.append(f"{template['test_name']}: Template rendering failed: {str(e)}")
        
        if issues:
            self.fail(f"Email template rendering issues found:\n" + "\n".join(issues))

    def test_jinja2_template_rendering(self):
        """Test Jinja2 templates with frappe.render_template"""
        if not frappe.db.exists("Email Template", "membership_applications_overdue"):
            self.skipTest("Test email template not found")
        
        try:
            template_doc = frappe.get_doc("Email Template", "membership_applications_overdue")
            
            # Test subject rendering
            rendered_subject = frappe.render_template(template_doc.subject, self.mock_data)
            self.assertIsInstance(rendered_subject, str)
            self.assertNotIn("{{", rendered_subject)  # Should not contain unparsed Jinja2
            
            # Test message rendering
            rendered_message = frappe.render_template(template_doc.response, self.mock_data)
            self.assertIsInstance(rendered_message, str)
            self.assertNotIn("{{", rendered_message)  # Should not contain unparsed Jinja2
            
        except Exception as e:
            self.fail(f"Jinja2 template rendering failed: {str(e)}")

    def test_email_template_completeness(self):
        """Test that all email templates have required fields"""
        issues = []
        
        # Get all email templates
        templates = frappe.get_all(
            "Email Template",
            filters={"enabled": 1},
            fields=["name", "subject", "response", "use_html"]
        )
        
        for template in templates:
            # Check required fields
            if not template.get("subject"):
                issues.append(f"Template '{template['name']}': Missing subject")
            
            if not template.get("response"):
                issues.append(f"Template '{template['name']}': Missing response/message")
            
            # Check for reasonable subject length
            subject = template.get("subject", "")
            if len(subject) > 200:
                issues.append(f"Template '{template['name']}': Subject too long ({len(subject)} chars)")
            
            if len(subject) < 5:
                issues.append(f"Template '{template['name']}': Subject too short")
        
        if issues:
            self.fail(f"Email template completeness issues found:\n" + "\n".join(issues))

    def _validate_jinja2_syntax(self, content, context):
        """Validate Jinja2 template syntax"""
        issues = []
        
        if not content:
            return issues
        
        # Check for unmatched Jinja2 brackets
        open_count = content.count("{{")
        close_count = content.count("}}")
        if open_count != close_count:
            issues.append(f"{context}: Unmatched Jinja2 brackets ({{ vs }})")
        
        # Check for unmatched control structures
        if_count = len(re.findall(r'{%\s*if\s+', content))
        endif_count = len(re.findall(r'{%\s*endif\s*%}', content))
        if if_count != endif_count:
            issues.append(f"{context}: Unmatched if/endif blocks")
        
        for_count = len(re.findall(r'{%\s*for\s+', content))
        endfor_count = len(re.findall(r'{%\s*endfor\s*%}', content))
        if for_count != endfor_count:
            issues.append(f"{context}: Unmatched for/endfor blocks")
        
        # Check for common syntax errors
        if "{ {" in content or "} }" in content:
            issues.append(f"{context}: Spaces in Jinja2 brackets")
        
        if re.search(r'{%[^%]*[^%\s]%}', content):
            issues.append(f"{context}: Missing spaces around Jinja2 control structures")
        
        return issues

    def _check_variable_consistency(self, subject, response, template_name):
        """Check for consistent variable naming between subject and response"""
        issues = []
        
        # Extract variables from subject and response
        subject_vars = set(re.findall(r'{{([^}]+)}}', subject))
        response_vars = set(re.findall(r'{{([^}]+)}}', response))
        
        # Clean up variable names (remove filters and whitespace)
        subject_vars = {var.split('|')[0].strip() for var in subject_vars}
        response_vars = {var.split('|')[0].strip() for var in response_vars}
        
        # Check for inconsistent variable naming patterns
        all_vars = subject_vars.union(response_vars)
        for var in all_vars:
            # Check for common naming inconsistencies
            if var.lower() != var and var.upper() != var:
                # Mixed case - check for consistency
                similar_vars = [v for v in all_vars if v.lower() == var.lower() and v != var]
                if similar_vars:
                    issues.append(f"{template_name}: Inconsistent variable casing: '{var}' vs {similar_vars}")
        
        return issues

    def _scan_python_email_syntax(self, content, file_path):
        """Scan Python content for email template syntax issues"""
        issues = []
        
        # Pattern 1: frappe.sendmail with subject containing { but not f-string
        pattern1 = r'frappe\.sendmail\s*\([^)]*subject\s*=\s*[^f]"[^"]*{[^{]'
        matches1 = re.finditer(pattern1, content, re.MULTILINE | re.DOTALL)
        for match in matches1:
            line_num = content[:match.start()].count('\n') + 1
            issues.append(f"{file_path}:{line_num}: frappe.sendmail subject may need f-string formatting")
        
        # Pattern 2: subject= with { but not f-string
        pattern2 = r'subject\s*=\s*[^f]"[^"]*{[^{]'
        matches2 = re.finditer(pattern2, content, re.MULTILINE | re.DOTALL)
        for match in matches2:
            line_num = content[:match.start()].count('\n') + 1
            issues.append(f"{file_path}:{line_num}: subject line may need f-string formatting")
        
        # Pattern 3: Variables used in message but commented out (more precise)
        pattern3 = r'#\s*(\w+_url)\s*=.*\n(.*{[^}]*\1[^}]*})'
        matches3 = re.finditer(pattern3, content, re.MULTILINE | re.DOTALL)
        for match in matches3:
            line_num = content[:match.start()].count('\n') + 1
            var_name = match.group(1)
            template_line = match.group(2).strip()
            # Only flag if the variable is actually used in a template context (not just defined elsewhere)
            if '{' + var_name + '}' in template_line:
                issues.append(f"{file_path}:{line_num}: Variable '{var_name}' is commented out but used in template")
        
        return issues


def run_email_template_validation():
    """
    Standalone function to run email template validation
    Can be called from pre-commit hooks or CI/CD
    """
    import unittest
    
    # Create test suite
    suite = unittest.TestSuite()
    suite.addTest(TestEmailTemplateValidation('test_email_fixture_templates_syntax'))
    suite.addTest(TestEmailTemplateValidation('test_python_email_templates_syntax'))
    suite.addTest(TestEmailTemplateValidation('test_email_template_variable_rendering'))
    suite.addTest(TestEmailTemplateValidation('test_jinja2_template_rendering'))
    suite.addTest(TestEmailTemplateValidation('test_email_template_completeness'))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    # Allow running as standalone script
    import sys
    success = run_email_template_validation()
    sys.exit(0 if success else 1)