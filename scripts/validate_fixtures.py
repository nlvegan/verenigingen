#!/usr/bin/env python3
"""
Fixture Schema Validation Script

Validates that fixture JSON files match their corresponding DocType field definitions
to prevent the "fixture fields don't exist in DocType" issues we encountered.

Usage:
    python scripts/validate_fixtures.py --fixture fixtures/critical_operation_rule.json
    python scripts/validate_fixtures.py --all
"""

import json
import os
import sys
from pathlib import Path


def load_doctype_schema(doctype_name):
    """Load DocType schema from the DocType JSON file"""
    doctype_path = Path(f"verenigingen/verenigingen/doctype/{doctype_name.lower().replace(' ', '_')}/{doctype_name.lower().replace(' ', '_')}.json")

    if not doctype_path.exists():
        raise FileNotFoundError(f"DocType definition not found: {doctype_path}")

    with open(doctype_path, 'r') as f:
        schema = json.load(f)

    # Extract valid field names from the DocType
    valid_fields = set()
    for field in schema.get('fields', []):
        valid_fields.add(field.get('fieldname'))

    # Add standard fields that are always valid
    standard_fields = {'name', 'doctype', 'docstatus', 'owner', 'modified_by', 'creation', 'modified'}
    valid_fields.update(standard_fields)

    return {
        'doctype': doctype_name,
        'valid_fields': valid_fields,
        'schema': schema
    }


def validate_fixture_against_schema(fixture_path, schema_info):
    """Validate a fixture file against its DocType schema"""
    print(f"\\n🔍 Validating fixture: {fixture_path}")

    with open(fixture_path, 'r') as f:
        fixture_data = json.load(f)

    if not isinstance(fixture_data, list):
        fixture_data = [fixture_data]

    errors = []
    warnings = []

    for i, record in enumerate(fixture_data):
        if not isinstance(record, dict):
            errors.append(f"Record {i}: Not a valid object")
            continue

        if record.get('doctype') != schema_info['doctype']:
            errors.append(f"Record {i}: DocType mismatch. Expected '{schema_info['doctype']}', got '{record.get('doctype')}'")
            continue

        # Check each field in the fixture record
        for field_name, field_value in record.items():
            if field_name not in schema_info['valid_fields']:
                errors.append(f"Record {i}: Field '{field_name}' does not exist in DocType '{schema_info['doctype']}'")
            elif field_value is None:
                warnings.append(f"Record {i}: Field '{field_name}' has null value")

    return errors, warnings


def get_doctype_from_fixture(fixture_path):
    """Extract DocType name from fixture file"""
    with open(fixture_path, 'r') as f:
        fixture_data = json.load(f)

    if isinstance(fixture_data, list) and len(fixture_data) > 0:
        return fixture_data[0].get('doctype')
    elif isinstance(fixture_data, dict):
        return fixture_data.get('doctype')

    return None


def validate_single_fixture(fixture_path):
    """Validate a single fixture file"""
    fixture_path = Path(fixture_path)

    if not fixture_path.exists():
        print(f"❌ Fixture file not found: {fixture_path}")
        return False

    try:
        # Extract DocType from fixture
        doctype_name = get_doctype_from_fixture(fixture_path)
        if not doctype_name:
            print(f"❌ Could not determine DocType from fixture: {fixture_path}")
            return False

        print(f"📋 Detected DocType: {doctype_name}")

        # Load DocType schema
        schema_info = load_doctype_schema(doctype_name)

        # Validate fixture against schema
        errors, warnings = validate_fixture_against_schema(fixture_path, schema_info)

        # Report results
        if errors:
            print(f"❌ VALIDATION FAILED: {len(errors)} errors found")
            for error in errors:
                print(f"   🔴 {error}")

        if warnings:
            print(f"⚠️  {len(warnings)} warnings:")
            for warning in warnings:
                print(f"   🟡 {warning}")

        if not errors and not warnings:
            print(f"✅ VALIDATION PASSED: Fixture is valid")
        elif not errors:
            print(f"✅ VALIDATION PASSED: {len(warnings)} warnings (non-blocking)")

        return len(errors) == 0

    except Exception as e:
        print(f"❌ VALIDATION ERROR: {str(e)}")
        return False


def validate_all_fixtures():
    """Validate all fixture files in the fixtures directory"""
    fixtures_dir = Path("verenigingen/fixtures")

    if not fixtures_dir.exists():
        print(f"❌ Fixtures directory not found: {fixtures_dir}")
        return False

    fixture_files = list(fixtures_dir.glob("*.json"))
    if not fixture_files:
        print("No fixture files found")
        return True

    print(f"🔍 Found {len(fixture_files)} fixture files")

    success_count = 0
    total_count = len(fixture_files)

    for fixture_file in fixture_files:
        if validate_single_fixture(fixture_file):
            success_count += 1

    print(f"\\n📊 SUMMARY: {success_count}/{total_count} fixtures passed validation")

    if success_count == total_count:
        print("🎉 ALL FIXTURES VALID!")
        return True
    else:
        print(f"💥 {total_count - success_count} fixtures failed validation")
        return False


def show_doctype_fields(doctype_name):
    """Show all valid fields for a DocType (debugging helper)"""
    try:
        schema_info = load_doctype_schema(doctype_name)
        print(f"\\n📋 Valid fields for DocType '{doctype_name}':")
        for field in sorted(schema_info['valid_fields']):
            print(f"   • {field}")
    except Exception as e:
        print(f"❌ Could not load DocType schema: {str(e)}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Validate fixture files against DocType schemas')
    parser.add_argument('--fixture', help='Path to specific fixture file to validate')
    parser.add_argument('--all', action='store_true', help='Validate all fixture files')
    parser.add_argument('--show-fields', help='Show valid fields for a DocType (debugging)')

    args = parser.parse_args()

    if args.show_fields:
        show_doctype_fields(args.show_fields)
        return

    if args.fixture:
        success = validate_single_fixture(args.fixture)
        sys.exit(0 if success else 1)
    elif args.all:
        success = validate_all_fixtures()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()