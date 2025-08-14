#!/usr/bin/env python3
"""
Simple test script for Member CSV Import functionality.
This script creates a sample CSV file and tests the import process.
"""

import csv
import io
import os
import tempfile


def create_sample_csv():
    """Create a sample CSV file for testing."""
    sample_data = [
        {
            "Lidnr.": "12345",
            "Voornaam": "Jan",
            "Achternaam": "Jansen",
            "Geboortedatum": "1990-01-15",
            "Inschrijfdataum": "2024-01-01",
            "Groep": "Amsterdam",
            "E-mailadres": "jan.jansen@example.com",
            "Telefoonnr.": "+31612345678",
            "Adres": "Hoofdstraat 123",
            "Plaats": "Amsterdam",
            "Postcode": "1000 AA",
            "Landcode": "NL",
            "IBAN": "NL91ABNA0417164300",
            "Contributiebedrag": "25.00",
            "Betaalperiode": "Maandelijks",
            "Betaald": "Ja",
            "Mollie CID": "cst_example123",
            "Mollie SID": "sub_example456",
            "Privacybeleid geaccepteerd": "Ja",
            "Lidmaatschapstype": "Standard",
        },
        {
            "Lidnr.": "12346",
            "Voornaam": "Marie",
            "Achternaam": "van der Berg",
            "Geboortedatum": "1985-05-20",
            "Inschrijfdataum": "2024-02-01",
            "Groep": "Rotterdam",
            "E-mailadres": "marie.vandenberg@example.com",
            "Telefoonnr.": "+31687654321",
            "Adres": "Kerkstraat 456",
            "Plaats": "Rotterdam",
            "Postcode": "3000 BB",
            "Landcode": "NL",
            "IBAN": "NL02RABO0123456789",
            "Contributiebedrag": "30.00",
            "Betaalperiode": "Jaarlijks",
            "Betaald": "Nee",
            "Mollie CID": "",
            "Mollie SID": "",
            "Privacybeleid geaccepteerd": "Ja",
            "Lidmaatschapstype": "Premium",
        },
    ]

    # Create temporary CSV file
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")

    writer = csv.DictWriter(temp_file, fieldnames=sample_data[0].keys())
    writer.writeheader()
    writer.writerows(sample_data)

    temp_file.close()
    return temp_file.name


def main():
    """Main test function."""
    print("Creating sample CSV file for Member Import testing...")

    csv_file = create_sample_csv()
    print(f"Sample CSV file created at: {csv_file}")

    print("\\nSample CSV content:")
    with open(csv_file, "r", encoding="utf-8") as f:
        print(f.read())

    print("\\nTo test the import:")
    print("1. Navigate to Member CSV Import in your Frappe system")
    print("2. Create a new Member CSV Import record")
    print("3. Upload the CSV file created above")
    print("4. Review the validation results")
    print("5. Enable test mode and process the import")
    print("6. If successful, disable test mode and run actual import")

    print(f"\\nCSV file path: {csv_file}")
    print("Remember to delete the temporary file when done testing!")


if __name__ == "__main__":
    main()
