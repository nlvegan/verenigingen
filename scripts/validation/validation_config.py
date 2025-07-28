#!/usr/bin/env python3
"""
Configuration for JavaScript-Python Parameter Validation System

This file contains configuration options for customizing the validation behavior
for different projects and use cases.
"""

# Files and directories to ignore during validation
IGNORE_PATTERNS = [
    # Version control and build artifacts
    '.git/*',
    '__pycache__/*',
    'node_modules/*',
    'dist/*',
    'build/*',
    '.vscode/*',
    '.idea/*',
    
    # Test files (can be enabled if needed)
    'cypress/*',
    'tests/frontend/*',
    '**/test_*.py',
    '**/test_*.js',
    
    # Legacy/archived code
    'archived_*/*',
    'legacy/*',
    'deprecated/*',
    
    # Specific to Frappe/ERPNext
    'public/dist/*',
    'assets/*',
]

# JavaScript patterns to recognize
JS_CALL_PATTERNS = [
    # Standard Frappe patterns
    r'frappe\.call\(\s*\{\s*method:\s*[\'"]([^\'"]+)[\'"]',
    r'frappe\.call\(\s*\{\s*[\'"]method[\'"]:\s*[\'"]([^\'"]+)[\'"]',
    
    # Form method calls
    r'frm\.call\(\s*\{\s*method:\s*[\'"]([^\'"]+)[\'"]',
    r'frm\.call\(\s*\{\s*[\'"]method[\'"]:\s*[\'"]([^\'"]+)[\'"]',
    
    # Direct method calls
    r'this\.call\(\s*[\'"]([^\'"]+)[\'"]',
    r'api\.call\(\s*[\'"]([^\'"]+)[\'"]',
    
    # Custom button handlers
    r'method:\s*[\'"]([^\'"]+)[\'"]',
    
    # Add custom patterns here for organization-specific code
]

# Parameter extraction patterns
ARGS_EXTRACTION_PATTERNS = [
    r'args:\s*\{([^}]+)\}',
    r'[\'"]args[\'"]:\s*\{([^}]+)\}',
]

# Issue severity configuration
SEVERITY_RULES = {
    'method_not_found': 'high',          # JavaScript calls to non-existent methods
    'missing_param': 'high',             # Missing required parameters
    'extra_param': 'medium',             # Extra parameters provided
    'param_count_mismatch': 'medium',    # Wrong number of parameters
    'type_mismatch': 'low',              # Potential type mismatches (future)
}

# Pre-commit hook configuration
PRE_COMMIT_CONFIG = {
    'block_on_critical': True,          # Block commits on critical issues
    'block_on_high': True,              # Block commits on high severity issues
    'block_on_medium': False,           # Allow commits with medium issues
    'block_on_low': False,              # Allow commits with low issues
    'max_issues_to_display': 10,        # Limit console output
    'require_full_scan': False,         # Full scan vs changed files only
}

# Output formatting
OUTPUT_CONFIG = {
    'default_format': 'text',           # text, json, html
    'show_stats': True,                 # Include statistics in output
    'show_examples': True,              # Show examples of found patterns
    'show_suggestions': True,           # Include fix suggestions
    'color_output': True,               # Use colored console output
}

# Performance optimization
PERFORMANCE_CONFIG = {
    'use_ast_parsing': True,            # Use AST for Python analysis (more accurate)
    'cache_results': True,              # Cache parsed results
    'parallel_processing': False,        # Enable parallel file processing
    'max_workers': 4,                   # Number of worker processes
    'incremental_scan': True,           # Only scan changed files when possible
}

def get_config():
    """Get complete configuration dictionary"""
    return {
        'ignore_patterns': IGNORE_PATTERNS,
        'js_call_patterns': JS_CALL_PATTERNS,
        'args_extraction_patterns': ARGS_EXTRACTION_PATTERNS,
        'severity_rules': SEVERITY_RULES,
        'pre_commit': PRE_COMMIT_CONFIG,
        'output': OUTPUT_CONFIG,
        'performance': PERFORMANCE_CONFIG,
    }

# Legacy field validation configuration (preserved for compatibility)
FIELD_VALIDATION_EXCEPTIONS = {
    "scripts/setup/auto_assign_profiles.py": ["Team Leader", "Leader"],
}

TEMPLATE_VALIDATION_EXCEPTIONS = {
    "verenigingen/templates/pages/workflow_demo.html": [
        "sample_members", "workflow_transitions", "workflow_states", 
        "workflow_stats", "title", "workflow", "transition", "error_message",
        "member", "state", "count"
    ],
}

ALLOWED_RISKY_PATTERNS = {
    "template.minimum_amount or 0": "Used for validation constraints, zero is acceptable",
    "getattr(settings, \"anbi_minimum_reportable_amount\", None)": "Settings field may not exist",
}

VALIDATION_SKIP_FILES = {
    "test_", "_test.py", "debug_", "_debug.py",
    "scripts/testing/", "scripts/debug/",
    "__pycache__", ".pyc"
}

CI_CONFIG = {
    "field_validation_timeout": 120,
    "template_validation_timeout": 180,
    "comprehensive_validation_timeout": 300,
    "max_violations_before_fail": {
        "field_validation": 0,
        "template_validation": 5,
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

if __name__ == "__main__":
    # Test configuration
    config = get_config()
    print("Configuration loaded successfully:")
    print(f"  - {len(config['ignore_patterns'])} ignore patterns")
    print(f"  - {len(config['js_call_patterns'])} JavaScript patterns")
    print(f"  - {len(config['severity_rules'])} severity rules")
    print("✅ Configuration validation passed")