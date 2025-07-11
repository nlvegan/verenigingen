"""
Unit tests to catch template syntax issues in Jinja2 + Vue.js templates
"""

import unittest
import os
import re
import frappe
from frappe.utils.jinja import get_jenv
from jinja2 import TemplateSyntaxError

class TestTemplateSyntax(unittest.TestCase):
    """Test template syntax for common issues"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.templates_dir = os.path.join(
            frappe.get_app_path("verenigingen"), 
            "templates", 
            "pages"
        )
    
    def test_jinja2_template_syntax(self):
        """Test that all Jinja2 templates have valid syntax"""
        template_files = self._get_template_files()
        
        for template_file in template_files:
            with self.subTest(template=template_file):
                try:
                    template_content = self._read_template_file(template_file)
                    
                    # Try to compile the template
                    jenv = get_jenv()
                    jenv.from_string(template_content)
                    
                except TemplateSyntaxError as e:
                    self.fail(f"Template syntax error in {template_file}: {e}")
                except Exception as e:
                    self.fail(f"Unexpected error in {template_file}: {e}")
    
    def test_vue_jinja_mixing_patterns(self):
        """Test for common Vue.js + Jinja2 mixing patterns that cause issues"""
        template_files = self._get_template_files()
        
        # Problematic patterns
        problematic_patterns = [
            # Vue.js logical OR in Jinja2 context
            (r'\{\{\s*[^}]*\|\|[^}]*\}\}', "Vue.js logical OR (||) in Jinja2 template"),
            
            # JavaScript template literals with Jinja2 translations
            (r'`[^`]*\{\{\s*_\([^}]*\}\}[^`]*`', "JavaScript template literal with Jinja2 translation"),
            
            # Vue.js v-model with Jinja2 translations
            (r'v-model\s*=\s*["\'][^"\']*\{\{\s*_\([^}]*\}\}[^"\']*["\']', "Vue.js v-model with Jinja2 translation"),
            
            # Nested template delimiters
            (r'\{\{[^}]*\{\{[^}]*\}\}[^}]*\}\}', "Nested template delimiters"),
        ]
        
        for template_file in template_files:
            template_content = self._read_template_file(template_file)
            
            for pattern, description in problematic_patterns:
                with self.subTest(template=template_file, pattern=description):
                    matches = re.findall(pattern, template_content)
                    if matches:
                        # Check if it's properly wrapped with {% raw %}
                        for match in matches:
                            if not self._is_in_raw_block(template_content, match):
                                self.fail(
                                    f"Problematic pattern found in {template_file}: {description}\n"
                                    f"Match: {match}\n"
                                    f"Consider wrapping with {{% raw %}} ... {{% endraw %}}"
                                )
    
    def test_expense_claim_template_specific(self):
        """Test expense claim template for specific issues"""
        template_file = os.path.join(self.templates_dir, "expense_claim_new.html")
        
        if not os.path.exists(template_file):
            self.skipTest("expense_claim_new.html not found")
        
        template_content = self._read_template_file(template_file)
        
        # Test for Vue.js expressions that should be wrapped in {% raw %}
        vue_expressions = [
            r'\{\{\s*line\.receipt_name\s*\|\|\s*__\([^}]*\}\}',
            r'\{\{\s*_\([^}]*\}\}\s*\$\{[^}]*\}',
            r'response\.message\?\.\w+\s*\|\|\s*["\'][^"\']*\{\{\s*_\([^}]*\}\}[^"\']*["\']',
            r'\{\{\s*totalAmount\.toFixed\(2\)\s*\}\}',
            r'\{\{\s*successMessage\s*\}\}',
            r'\{\{\s*[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*\([^}]*\)\s*\}\}',  # Vue method calls
            r'\{\{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\}\}(?!\s*</)',  # Vue variables (not followed by closing tag)
        ]
        
        for pattern in vue_expressions:
            matches = re.findall(pattern, template_content)
            for match in matches:
                with self.subTest(expression=match):
                    self.assertTrue(
                        self._is_in_raw_block(template_content, match),
                        f"Vue.js expression should be wrapped in {{% raw %}} block: {match}"
                    )
    
    def test_template_compilation_with_context(self):
        """Test template compilation with realistic context"""
        template_file = os.path.join(self.templates_dir, "expense_claim_new.html")
        
        if not os.path.exists(template_file):
            self.skipTest("expense_claim_new.html not found")
        
        template_content = self._read_template_file(template_file)
        
        # Mock context that would be passed to template
        mock_context = {
            "show_form": True,
            "error_message": "",
            "_": lambda x: x,  # Mock translation function
            "__": lambda x: x,  # Mock translation function
        }
        
        try:
            jenv = get_jenv()
            template = jenv.from_string(template_content)
            rendered = template.render(mock_context)
            
            # Basic checks that rendering worked
            self.assertIn("expense-claim-form", rendered)
            self.assertIn("Vue", rendered)
            
        except Exception as e:
            self.fail(f"Template compilation failed with context: {e}")
    
    def test_javascript_syntax_in_templates(self):
        """Test for basic JavaScript syntax errors in templates"""
        template_files = self._get_template_files()
        
        for template_file in template_files:
            template_content = self._read_template_file(template_file)
            
            # Find JavaScript blocks
            js_blocks = re.findall(r'<script[^>]*>(.*?)</script>', template_content, re.DOTALL)
            
            for js_block in js_blocks:
                with self.subTest(template=template_file, block="JavaScript"):
                    # Check for common syntax issues
                    self._check_js_syntax(js_block, template_file)
    
    def _get_template_files(self):
        """Get all template files to test"""
        template_files = []
        
        for root, dirs, files in os.walk(self.templates_dir):
            for file in files:
                if file.endswith(".html"):
                    template_files.append(os.path.join(root, file))
        
        return template_files
    
    def _read_template_file(self, template_file):
        """Read template file content"""
        with open(template_file, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _is_in_raw_block(self, content, text):
        """Check if text is within a {% raw %} block"""
        # Find the position of the text
        text_pos = content.find(text)
        if text_pos == -1:
            return False
        
        # Find all raw blocks
        raw_blocks = re.finditer(r'\{\%\s*raw\s*\%\}(.*?)\{\%\s*endraw\s*\%\}', content, re.DOTALL)
        
        for block in raw_blocks:
            if block.start() <= text_pos <= block.end():
                return True
        
        return False
    
    def _check_js_syntax(self, js_code, template_file):
        """Check JavaScript code for common syntax issues"""
        # Remove Vue.js template parts and Jinja2 parts for basic JS checking
        cleaned_js = re.sub(r'\{\{[^}]*\}\}', '""', js_code)
        cleaned_js = re.sub(r'\{\%[^%]*\%\}', '', cleaned_js)
        
        # Check for common issues
        common_issues = [
            (r'console\.log\s*\(', "Console.log statements should be removed for production"),
            (r'debugger\s*;', "Debugger statements should be removed for production"),
            (r'alert\s*\(', "Alert statements should be replaced with frappe.msgprint"),
        ]
        
        for pattern, message in common_issues:
            if re.search(pattern, cleaned_js):
                print(f"Warning in {template_file}: {message}")


@frappe.whitelist()
def run_template_syntax_tests():
    """Run template syntax tests via API"""
    import sys
    from io import StringIO
    
    # Capture test output
    test_output = StringIO()
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTemplateSyntax)
    
    # Run tests
    runner = unittest.TextTestRunner(stream=test_output, verbosity=2)
    result = runner.run(suite)
    
    # Get output
    output = test_output.getvalue()
    
    return {
        "success": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "output": output,
        "failure_details": [str(failure) for failure in result.failures],
        "error_details": [str(error) for error in result.errors]
    }


if __name__ == "__main__":
    unittest.main()