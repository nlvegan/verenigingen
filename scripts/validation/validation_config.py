#!/usr/bin/env python3
"""
Validation Configuration
Manages validation rules, exceptions, and bypass mechanisms
"""

# Known false positives for field validation
FIELD_VALIDATION_EXCEPTIONS = {
    # File path: [list of acceptable "field" names that aren't actually fields]
    "scripts/setup/auto_assign_profiles.py": ["Team Leader", "Leader"],
    # Add more exceptions as needed
}

# Known false positives for template validation
TEMPLATE_VALIDATION_EXCEPTIONS = {
    # Template file: [list of acceptable missing variables]
    "verenigingen/templates/pages/workflow_demo.html": [
        "sample_members", "workflow_transitions", "workflow_states", 
        "workflow_stats", "title", "workflow", "transition", "error_message",
        "member", "state", "count"
    ],
    # Add more template exceptions as needed
}

# Risky patterns that should be allowed (with justification)
ALLOWED_RISKY_PATTERNS = {
    # Pattern: reason
    "template.minimum_amount or 0": "Used for validation constraints, zero is acceptable",
    "getattr(settings, \"anbi_minimum_reportable_amount\", None)": "Settings field may not exist",
    # Add more allowed patterns as needed
}

# Files to completely skip validation for
VALIDATION_SKIP_FILES = {
    # Skip test files, debug files, etc.
    "test_", "_test.py", "debug_", "_debug.py",
    "scripts/testing/", "scripts/debug/",
    "__pycache__", ".pyc"
}

# CI/CD configuration
CI_CONFIG = {
    "field_validation_timeout": 120,  # 2 minutes
    "template_validation_timeout": 180,  # 3 minutes
    "comprehensive_validation_timeout": 300,  # 5 minutes
    "max_violations_before_fail": {
        "field_validation": 0,  # Strict: no field violations allowed
        "template_validation": 5,  # Allow some template violations
    }
}

def should_skip_file(file_path: str) -> bool:
    """Check if a file should be skipped during validation"""
    for skip_pattern in VALIDATION_SKIP_FILES:
        if skip_pattern in file_path:
            return True
    return False

def is_known_field_exception(file_path: str, field_name: str) -> bool:
    """Check if a field violation is a known exception"""
    exceptions = FIELD_VALIDATION_EXCEPTIONS.get(file_path, [])
    return field_name in exceptions

def is_known_template_exception(template_path: str, variable_name: str) -> bool:
    """Check if a template variable violation is a known exception"""
    exceptions = TEMPLATE_VALIDATION_EXCEPTIONS.get(template_path, [])
    return variable_name in exceptions

def is_allowed_risky_pattern(code_line: str) -> bool:
    """Check if a risky pattern is explicitly allowed"""
    for pattern in ALLOWED_RISKY_PATTERNS:
        if pattern in code_line:
            return True
    return False