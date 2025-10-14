"""
Script to add missing email templates to the fixtures file.

This adds the 4 donation-related templates that were created as HTML files
but not yet added to the Email Template fixture.
"""

import json
from pathlib import Path

# Get paths
app_path = Path(__file__).parent.parent
fixture_file = app_path / "verenigingen" / "fixtures" / "email_template.json"
templates_dir = app_path / "verenigingen" / "templates" / "emails"

# Read existing fixtures
with open(fixture_file, 'r', encoding='utf-8') as f:
    fixtures = json.load(f)

print(f"Found {len(fixtures)} existing email templates")

# Templates to add (name: {subject, reference_doctype})
new_templates = {
    "periodic_agreement_confirmation": {
        "subject": "Periodic Donation Agreement Confirmation - {{ agreement_number|e }}",
        "reference_doctype": "Periodic Donation Agreement"
    },
    "periodic_agreement_expiry": {
        "subject": "Your Donation Agreement Expires in {{ days_remaining }} Days",
        "reference_doctype": "Periodic Donation Agreement"
    },
    "periodic_agreement_cancellation": {
        "subject": "Periodic Donation Agreement Cancelled - {{ agreement_number|e }}",
        "reference_doctype": "Periodic Donation Agreement"
    },
    "anbi_consent_request": {
        "subject": "ANBI Consent Request - Tax Benefits for Your Donations",
        "reference_doctype": "Donor"
    }
}

# Check which templates already exist
existing_names = {template['name'] for template in fixtures}
templates_to_add = []

for template_name, template_config in new_templates.items():
    if template_name in existing_names:
        print(f"⏭️  Template '{template_name}' already exists, skipping")
        continue

    # Read HTML file
    html_file = templates_dir / f"{template_name}.html"
    if not html_file.exists():
        print(f"❌ HTML file not found: {html_file}")
        continue

    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # Create template entry
    template_entry = {
        "docstatus": 0,
        "doctype": "Email Template",
        "enabled": 1,
        "name": template_name,
        "reference_doctype": template_config["reference_doctype"],
        "response": None,
        "response_html": html_content,
        "subject": template_config["subject"],
        "use_html": 1
    }

    templates_to_add.append(template_entry)
    print(f"✅ Prepared template: {template_name}")

if templates_to_add:
    # Add new templates to fixtures
    fixtures.extend(templates_to_add)

    # Write back to file
    with open(fixture_file, 'w', encoding='utf-8') as f:
        json.dump(fixtures, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Added {len(templates_to_add)} templates to fixture file")
    print(f"📊 Total templates in fixture: {len(fixtures)}")
    print("\nRun this command to load the templates:")
    print(f"  bench --site dev.veganisme.net import-doc {fixture_file}")
else:
    print("\n✅ All templates already exist in fixture file")
