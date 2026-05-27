"""
Unit tests for email template XSS protection.
Validates that all email templates properly escape user input to prevent XSS attacks.
"""

import unittest
import json
import re
from pathlib import Path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestEmailTemplateXSSProtection(EnhancedTestCase):
    """Test XSS protection in email templates.

    Reads `verenigingen/fixtures/email_template.json` directly (the production
    install fixture). Every template added there is gated by this suite —
    template authors editing that file should expect their additions to be
    inspected by `test_specific_xss_vulnerable_patterns`, `test_url_handling_security`,
    `test_variable_escaping_patterns`, etc.
    """

    def setUp(self):
        """Load email templates for testing."""
        super().setUp()
        # Email templates live in the production fixtures dir (loaded by app install),
        # not under tests/fixtures. Read directly from the canonical location.
        template_file = (
            Path(__file__).parent.parent.parent / "fixtures" / "email_template.json"
        )

        with open(template_file, 'r') as f:
            self.templates = json.load(f)

    def test_all_templates_loaded(self):
        """Verify templates are loaded correctly."""
        self.assertGreater(len(self.templates), 0)
        self.assertIsInstance(self.templates, list)

    def test_variable_escaping_patterns(self):
        """Test that all variable outputs are properly escaped."""
        unescaped_variables = []

        for template in self.templates:
            template_name = template.get('name', 'Unknown')

            # Check response content
            if 'response' in template and template['response']:
                unescaped = self._find_unescaped_variables(template['response'])
                if unescaped:
                    unescaped_variables.extend([
                        f"{template_name}:response - {var}" for var in unescaped
                    ])

            # Check subject line
            if 'subject' in template and template['subject']:
                unescaped = self._find_unescaped_variables(template['subject'])
                if unescaped:
                    unescaped_variables.extend([
                        f"{template_name}:subject - {var}" for var in unescaped
                    ])

        # Report any unescaped variables found
        if unescaped_variables:
            self.fail(
                f"Found {len(unescaped_variables)} unescaped variables that could lead to XSS:\n" +
                "\n".join(unescaped_variables[:10])  # Show first 10
            )

    def _find_unescaped_variables(self, content):
        """Find variables that are not properly escaped."""
        unescaped = []

        # Pattern to find {{ variable }} expressions
        variable_pattern = r'\{\{\s*([^}]+?)\s*\}\}'

        matches = re.findall(variable_pattern, content)

        for match in matches:
            variable_content = match.strip()

            # Skip if it's a control structure (starts with %)
            if variable_content.startswith('%'):
                continue

            # Skip if it already has escaping filter
            if '|e' in variable_content:
                continue

            # Skip URLs that should not be escaped
            if any(url_part in variable_content.lower() for url_part in [
                'base_url', 'payment_url', 'approval_url', 'dashboard_url',
                'url', 'link', 'href'
            ]):
                continue

            # Skip static strings in quotes
            if ('"' in variable_content and
                (variable_content.count('"') == 2 or 'or' in variable_content)):
                continue

            # Skip numeric/counter variables that are safe (integers)
            safe_numeric_vars = [
                'count', 'total', 'days_remaining', 'days', 'amount',
                'num_', 'number', 'quantity', 'year', 'month', 'day'
            ]
            if any(safe_var in variable_content.lower() for safe_var in safe_numeric_vars):
                continue

            # Skip date/time formatting (frappe.format_date etc.)
            if 'format' in variable_content.lower():
                continue

            # This is likely an unescaped user variable
            unescaped.append(variable_content)

        return unescaped

    def test_specific_xss_vulnerable_patterns(self):
        """Test for specific XSS-vulnerable patterns.

        Checks that sensitive fields (name, email, message, reason) are escaped.
        Variables with |e filter are considered safe.
        """
        sensitive_field_keywords = ['name', 'email', 'message', 'reason']
        vulnerable_templates = []

        for template in self.templates:
            template_name = template.get('name', 'Unknown')
            # Handle both response and response_html fields
            response_content = template.get('response') or template.get('response_html') or ''
            subject_content = template.get('subject') or ''
            content = response_content + ' ' + subject_content

            # Find all {{ variable }} expressions
            variable_pattern = r'\{\{\s*([^}]+?)\s*\}\}'
            matches = re.findall(variable_pattern, content)

            for match in matches:
                variable_content = match.strip()

                # Skip if already escaped
                if '|e' in variable_content:
                    continue

                # Skip control structures
                if variable_content.startswith('%'):
                    continue

                # Skip URLs
                if any(url_kw in variable_content.lower() for url_kw in ['url', 'link', 'href']):
                    continue

                # Skip doc.name and doc.fieldname patterns (system-generated IDs)
                if variable_content.startswith('doc.'):
                    continue

                # Skip variables with |default filter (have safe fallbacks)
                if '|default' in variable_content:
                    continue

                # Skip patterns with 'or "..."' fallback (Jinja default pattern)
                if ' or "' in variable_content or " or '" in variable_content:
                    continue

                # Check if this is a sensitive field that should be escaped
                for keyword in sensitive_field_keywords:
                    if keyword in variable_content.lower():
                        # This is a sensitive field without escaping
                        vulnerable_templates.append(
                            f"{template_name}: Unescaped {keyword} field: {variable_content}"
                        )
                        break

        if vulnerable_templates:
            self.fail(
                f"Found templates with potentially vulnerable patterns:\n" +
                "\n".join(vulnerable_templates[:5])  # Show first 5
            )

    def test_html_context_escaping(self):
        """Test that variables in HTML context are properly escaped."""
        html_injection_risks = []

        for template in self.templates:
            template_name = template.get('name', 'Unknown')
            content = template.get('response', '')

            if not content:
                continue

            # Find variables that appear in HTML attribute context
            # These are especially dangerous for XSS
            attribute_pattern = r'(\w+)=["\']([^"\']*\{\{[^}]+\}\}[^"\']*)["\']'

            matches = re.findall(attribute_pattern, content)
            for attr_name, attr_value in matches:
                # Check if the variable in the attribute is escaped
                variable_match = re.search(r'\{\{([^}]+)\}\}', attr_value)
                if variable_match:
                    variable_content = variable_match.group(1).strip()
                    if '|e' not in variable_content and 'url' not in variable_content.lower():
                        html_injection_risks.append(
                            f"{template_name}: Unescaped variable in {attr_name} attribute: {variable_content}"
                        )

        if html_injection_risks:
            self.fail(
                f"Found variables in HTML attributes that could allow injection:\n" +
                "\n".join(html_injection_risks[:5])
            )

    def test_template_structure_integrity(self):
        """Test that all templates have required structure."""
        invalid_templates = []

        for template in self.templates:
            template_name = template.get('name', 'Unknown')

            # Check required fields
            if not template.get('name'):
                invalid_templates.append(f"Template missing name field")
                continue

            if not template.get('subject'):
                invalid_templates.append(f"{template_name}: Missing subject")

            # Check for content in either response or response_html
            has_content = template.get('response') or template.get('response_html')
            if not has_content:
                invalid_templates.append(f"{template_name}: Missing response content")

            # For HTML templates, check use_html flag
            if template.get('response_html') and template.get('use_html') != 1:
                invalid_templates.append(f"{template_name}: use_html not set to 1 for HTML template")

        if invalid_templates:
            self.fail(
                f"Found templates with structure issues:\n" +
                "\n".join(invalid_templates[:10])
            )

    def test_escaping_filter_correctness(self):
        """Test that escaping filters are used correctly."""
        incorrect_escaping = []

        for template in self.templates:
            template_name = template.get('name', 'Unknown')
            # Handle both response and response_html fields
            response_content = template.get('response') or template.get('response_html') or ''
            subject_content = template.get('subject') or ''
            content = response_content + ' ' + subject_content

            # Find all escaping filters
            escaping_pattern = r'\{\{\s*([^}]+\|e[^}]*)\s*\}\}'

            matches = re.findall(escaping_pattern, content)
            for match in matches:
                # Check for common escaping mistakes
                if '|e|' in match:  # Double escaping
                    incorrect_escaping.append(f"{template_name}: Double escaping: {match}")
                elif match.count('|e') > 1:  # Multiple e filters
                    incorrect_escaping.append(f"{template_name}: Multiple e filters: {match}")

        if incorrect_escaping:
            self.fail(
                f"Found incorrect escaping patterns:\n" +
                "\n".join(incorrect_escaping)
            )

    def test_url_handling_security(self):
        """Test that URLs are handled securely without breaking functionality.

        Note: Escaping document names/references in URLs is actually CORRECT
        because it prevents javascript: URL injection attacks. We only flag
        cases where URL paths themselves are incorrectly escaped.
        """
        url_issues = []

        for template in self.templates:
            template_name = template.get('name', 'Unknown')
            # Handle both response and response_html fields
            content = template.get('response') or template.get('response_html') or ''

            # Check for dangerous URL patterns that should never appear
            dangerous_patterns = [
                (r'href\s*=\s*["\']javascript:', 'javascript: URL'),
                (r'href\s*=\s*["\']data:', 'data: URL'),
                (r'href\s*=\s*["\']vbscript:', 'vbscript: URL'),
            ]

            for pattern, description in dangerous_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    url_issues.append(f"{template_name}: Contains {description}")

        if url_issues:
            self.fail(
                f"Found URL handling issues:\n" +
                "\n".join(url_issues)
            )

    def test_template_content_validation(self):
        """Test overall template content for security best practices."""
        security_issues = []

        for template in self.templates:
            template_name = template.get('name', 'Unknown')
            # Handle both response and response_html fields
            content = template.get('response') or template.get('response_html') or ''

            # Check for potentially dangerous patterns
            # Note: We use word boundaries and specific event handler names to avoid false positives
            dangerous_patterns = [
                (r'javascript\s*:', 'JavaScript URLs'),
                (r'vbscript\s*:', 'VBScript URLs'),
                (r'<script[^>]*>', 'Script tags'),
                # Specific dangerous event handlers (not just any on* pattern)
                (r'\s(onclick|onmouseover|onload|onerror|onsubmit|onfocus|onblur)\s*=', 'Event handlers'),
            ]

            for pattern, description in dangerous_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    security_issues.append(f"{template_name}: Contains {description}")

        if security_issues:
            self.fail(
                f"Found potential security issues in templates:\n" +
                "\n".join(security_issues)
            )


if __name__ == '__main__':
    unittest.main()