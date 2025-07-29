#!/usr/bin/env python3
"""
Test Suite for Advanced JavaScript Field Validator
==================================================

Comprehensive test suite to ensure the validator correctly handles:
1. Legitimate JavaScript code (should PASS with 0 issues)
2. Actual DocType field reference issues (should FAIL appropriately)
3. Edge cases and complex patterns

This ensures the validator achieves 0% false positives while catching real issues.
"""

import tempfile
import os
from advanced_javascript_field_validator import AdvancedJavaScriptFieldValidator


class TestAdvancedJavaScriptValidator:
    """Test suite for the advanced JavaScript validator"""
    
    def __init__(self):
        self.validator = AdvancedJavaScriptFieldValidator()
        self.test_results = []
    
    def test_legitimate_code_patterns(self):
        """Test patterns that should NOT trigger validation errors (0% false positives)"""
        
        # These are legitimate JavaScript patterns that were causing false positives
        legitimate_patterns = [
            # API response access patterns
            '''
            frappe.call({
                method: "get_member_expulsion_history",
                callback: function(response) {
                    response.message.forEach(function(d) {
                        console.log(d.member); // Should NOT be flagged
                        console.log(d.name);   // Should NOT be flagged
                    });
                }
            });
            ''',
            
            # Promise callback patterns
            '''
            frappe.db.get_value('Member', filters, ['name', 'email']).then(function(result) {
                if (result.message && result.message.name) {
                    console.log(result.message.name); // Should NOT be flagged
                    console.log(result.message.email); // Should NOT be flagged
                }
            });
            ''',
            
            # Arrow function patterns
            '''
            frappe.db.get_list('Membership Termination Request', {
                filters: {status: 'Executed'},
                fields: ['member']
            }).then(r => r.map(d => d.member)); // Should NOT be flagged
            ''',
            
            # Array iteration patterns
            '''
            items.forEach(function(item) {
                console.log(item.member);     // Should NOT be flagged
                console.log(item.custom_field); // Should NOT be flagged
            });
            ''',
            
            # Generic object access
            '''
            const data = response.data;
            const config = {member: "test"};
            console.log(data.member);     // Should NOT be flagged
            console.log(config.member);   // Should NOT be flagged
            ''',
            
            # jQuery/DOM patterns
            '''
            $element.data('member-id');     // Should NOT be flagged
            element.member = "test";        // Should NOT be flagged
            ''',
        ]
        
        for i, pattern in enumerate(legitimate_patterns):
            result = self._test_pattern(
                pattern, 
                f"legitimate_pattern_{i}", 
                expected_issues=0,
                description="Should NOT trigger validation errors"
            )
            self.test_results.append(result)
    
    def test_actual_field_reference_issues(self):
        """Test patterns that SHOULD trigger validation errors (catch real issues)"""
        
        # These are actual DocType field reference issues that should be caught
        problematic_patterns = [
            # Invalid field in frm.set_value
            '''
            frappe.ui.form.on('Member', {
                refresh: function(frm) {
                    frm.set_value("nonexistent_field", "value"); // Should be flagged
                }
            });
            ''',
            
            # Invalid field in frm.get_field
            '''
            frappe.ui.form.on('SEPA Mandate', {
                validate: function(frm) {
                    frm.get_field("invalid_field").hidden = 1; // Should be flagged
                }
            });
            ''',
            
            # Invalid field in frappe.model.get_value
            '''
            frappe.model.get_value("Member", member_name, "fake_field", function(r) {
                // Should be flagged
                console.log(r.message.fake_field);
            });
            ''',
            
            # Invalid field in fields array
            '''
            frappe.db.get_list("Member", {
                fields: ["name", "nonexistent_field"], // Should be flagged
                filters: {}
            });
            ''',
        ]
        
        for i, pattern in enumerate(problematic_patterns):
            result = self._test_pattern(
                pattern, 
                f"problematic_pattern_{i}", 
                expected_issues=1,  # Should catch 1 issue
                description="Should trigger validation errors for invalid fields"
            )
            self.test_results.append(result)
    
    def test_edge_cases(self):
        """Test edge cases to ensure robust validation"""
        
        edge_cases = [
            # Mixed legitimate and problematic code
            '''
            frappe.ui.form.on('Member', {
                refresh: function(frm) {
                    // Legitimate API response access
                    frappe.call({
                        method: "get_data",
                        callback: function(response) {
                            response.message.forEach(d => console.log(d.member)); // OK
                        }
                    });
                    
                    // Actual field reference issue
                    frm.set_value("nonexistent_field", "test"); // Should be flagged
                }
            });
            ''',
            
            # Complex nested patterns
            '''
            frappe.call({
                method: "complex_method",
                callback: function(response) {
                    const data = response.message || {};
                    if (data.items) {
                        data.items.filter(item => item.member)  // OK
                                  .map(item => {
                                      return {
                                          name: item.name,        // OK
                                          member: item.member     // OK
                                      };
                                  });
                    }
                }
            });
            ''',
        ]
        
        for i, pattern in enumerate(edge_cases):
            result = self._test_pattern(
                pattern, 
                f"edge_case_{i}", 
                expected_issues=1 if i == 0 else 0,  # First case has 1 issue
                description="Should handle complex edge cases correctly"
            )
            self.test_results.append(result)
    
    def _test_pattern(self, code: str, test_name: str, expected_issues: int, description: str) -> dict:
        """
        Test a specific code pattern
        
        Args:
            code: JavaScript code to test
            test_name: Name of the test
            expected_issues: Expected number of validation issues
            description: Test description
            
        Returns:
            Test result dictionary
        """
        # Create temporary file with the test code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        try:
            # Validate the temporary file
            issues = self.validator.validate_javascript_file(temp_file)
            actual_issues = len(issues)
            
            # Check if result matches expectation
            passed = actual_issues == expected_issues
            
            result = {
                'test_name': test_name,
                'description': description,
                'expected_issues': expected_issues,
                'actual_issues': actual_issues,
                'passed': passed,
                'issues': issues if issues else None
            }
            
            return result
            
        finally:
            # Clean up temporary file
            os.unlink(temp_file)
    
    def run_all_tests(self):
        """Run all test suites"""
        print("🧪 Testing Advanced JavaScript Field Validator")
        print("=" * 50)
        print()
        
        print("1. Testing legitimate code patterns (should have 0 false positives)...")
        self.test_legitimate_code_patterns()
        
        print("2. Testing actual field reference issues (should catch real problems)...")
        self.test_actual_field_reference_issues()
        
        print("3. Testing edge cases...")
        self.test_edge_cases()
        
        print("\n" + "=" * 50)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 50)
        
        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results if r['passed']])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print()
        
        if failed_tests > 0:
            print("FAILED TESTS:")
            print("-" * 30)
            for result in self.test_results:
                if not result['passed']:
                    print(f"❌ {result['test_name']}: {result['description']}")
                    print(f"   Expected {result['expected_issues']} issues, got {result['actual_issues']}")
                    if result['issues']:
                        for issue in result['issues']:
                            print(f"   - Line {issue.line_number}: {issue.description}")
                    print()
        
        print("PASSED TESTS:")
        print("-" * 30)
        for result in self.test_results:
            if result['passed']:
                print(f"✅ {result['test_name']}: Expected {result['expected_issues']}, got {result['actual_issues']}")
        
        print(f"\n🎯 VALIDATION SUCCESS RATE: {(passed_tests/total_tests)*100:.1f}%")
        
        # Check for false positives (legitimate code flagged as issues)
        false_positives = [r for r in self.test_results 
                          if 'legitimate' in r['test_name'] and not r['passed']]
        
        print(f"🚨 FALSE POSITIVE RATE: {(len(false_positives)/total_tests)*100:.1f}%")
        
        return failed_tests == 0


def main():
    """Run the comprehensive test suite"""
    tester = TestAdvancedJavaScriptValidator()
    success = tester.run_all_tests()
    
    if success:
        print("\n🎉 ALL TESTS PASSED! Validator is working correctly.")
        print("✅ 0% False Positive Rate Achieved")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED! Validator needs refinement.")
        return 1


if __name__ == "__main__":
    exit(main())