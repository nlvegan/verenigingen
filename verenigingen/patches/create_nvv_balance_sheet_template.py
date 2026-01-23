"""
Create NVV Balance Sheet Financial Report Template

This patch creates a Balance Sheet template matching the NVV Jaarrekening structure.
Can be run via: bench --site veg11.veganisme.org execute verenigingen.patches.create_nvv_balance_sheet_template.execute
"""

import frappe


def execute():
    """Create the NVV Balance Sheet Financial Report Template."""
    if frappe.db.exists("Financial Report Template", "NVV Balans"):
        frappe.delete_doc("Financial Report Template", "NVV Balans", force=True)
        print("Deleted existing template")

    template = frappe.new_doc("Financial Report Template")
    template.template_name = "NVV Balans"
    template.report_type = "Balance Sheet"
    template.disabled = 0

    # Build the rows
    rows = []
    idx = 1

    def add_row(
        ref_code="",
        display_name="",
        indent=0,
        data_source="Account Data",
        balance_type="Closing Balance",
        formula="",
        bold=False,
        italic=False,
        hide_empty=False,
        hidden=False,
        reverse_sign=False,
    ):
        nonlocal idx
        row = {
            "idx": idx,
            "reference_code": ref_code,
            "display_name": display_name,
            "indentation_level": indent,
            "data_source": data_source,
            "balance_type": balance_type if data_source == "Account Data" else "",
            "calculation_formula": formula,
            "bold_text": 1 if bold else 0,
            "italic_text": 1 if italic else 0,
            "hide_when_empty": 1 if hide_empty else 0,
            "hidden_calculation": 1 if hidden else 0,
            "reverse_sign": 1 if reverse_sign else 0,
        }
        rows.append(row)
        idx += 1
        return row

    def add_blank():
        add_row(data_source="Blank Line")

    # ============================================
    # ACTIVA (Assets)
    # ============================================

    # --- Vaste Activa (Fixed Assets) ---
    # Immateriële vaste activa - typically intangible assets (software, licenses)
    # NVV doesn't have these, but include for completeness
    add_row(
        ref_code="IMMAT_VA",
        display_name="Immateriële vaste activa",
        indent=0,
        formula='["account_type", "=", "Intangible Asset"]',
        hide_empty=True,
    )

    # Materiële vaste activa - Fixed assets (0060-0075) minus accumulated depreciation
    # NVV uses accounts 0060-0075 for fixed assets, but they're typed as "Current Asset"
    # so we match by account_number pattern instead
    add_row(
        ref_code="MAT_VA_BRUTO",
        display_name="",
        formula='{"or": [["account_type", "=", "Fixed Asset"], {"and": [["account_number", "like", "006%"], ["account_number", "not like", "%5"]]}]}',
        hidden=True,
    )
    add_row(
        ref_code="MAT_VA_AFSCHR",
        display_name="",
        formula='{"or": [["account_type", "=", "Accumulated Depreciation"], {"and": [["account_number", "like", "006%"], ["account_number", "like", "%5"]]}, {"and": [["account_number", "like", "007%"], ["account_number", "like", "%5"]]}]}',
        hidden=True,
    )
    add_row(
        ref_code="MAT_VA",
        display_name="Materiële vaste activa",
        indent=0,
        data_source="Calculated Amount",
        formula="MAT_VA_BRUTO + MAT_VA_AFSCHR",
        hide_empty=True,
    )

    # Financiële vaste activa - long-term investments
    add_row(
        ref_code="FIN_VA",
        display_name="Financiële vaste activa",
        indent=0,
        formula='{"and": [["root_type", "=", "Asset"], ["account_type", "like", "%Investment%"]]}',
        hide_empty=True,
    )

    # Subtotal: Vaste activa
    add_row(
        ref_code="VASTE_ACTIVA",
        display_name="Vaste activa",
        indent=0,
        data_source="Calculated Amount",
        formula="IMMAT_VA + MAT_VA + FIN_VA",
        bold=True,
    )

    add_blank()

    # --- Vlottende Activa (Current Assets) ---

    # Voorraden (Stock/Inventory) - accounts 3000, 3010
    add_row(
        ref_code="VOORRADEN",
        display_name="Voorraden",
        indent=0,
        formula='{"or": [["account_type", "=", "Stock"], ["account_number", "like", "30%"]]}',
    )

    # Vorderingen (Receivables) - accounts 1300-1350, 1380-1385 (Overlopende posten), 1480-1490 (prepaid)
    add_row(
        ref_code="VORDERINGEN",
        display_name="Vorderingen",
        indent=0,
        formula='{"or": [["account_type", "=", "Receivable"], ["account_number", "like", "138%"], {"and": [["root_type", "=", "Asset"], ["account_number", "like", "14%"]]}]}',
    )

    # Liquide middelen (Cash & Bank) - accounts 1000-1160, also ING spaarrekening (no number)
    # Include Mollie Uitbetalingen (1139) which is typed as Current Asset
    add_row(
        ref_code="LIQUIDE",
        display_name="Liquide middelen",
        indent=0,
        formula='{"or": [["account_type", "=", "Bank"], ["account_type", "=", "Cash"], ["account_number", "=", "1139"], ["account_name", "like", "%spaarrekening%"]]}',
    )

    # Tussenrekeningen (Kruisposten / clearing accounts) - account 2000
    # Should ideally be zero at period end
    add_row(
        ref_code="TUSSENREK",
        display_name="Tussenrekeningen",
        indent=0,
        formula='["account_type", "=", "Temporary"]',
        hide_empty=True,
    )

    # Subtotal: Vlottende activa
    add_row(
        ref_code="VLOTTENDE_ACTIVA",
        display_name="Vlottende activa",
        indent=0,
        data_source="Calculated Amount",
        formula="VOORRADEN + VORDERINGEN + LIQUIDE + TUSSENREK",
        bold=True,
    )

    add_blank()

    # TOTAL ASSETS
    add_row(
        ref_code="TOTAAL_ACTIVA",
        display_name="Totaal activa",
        indent=0,
        data_source="Calculated Amount",
        formula="VASTE_ACTIVA + VLOTTENDE_ACTIVA",
        bold=True,
    )

    add_blank()

    # ============================================
    # PASSIVA (Liabilities & Equity)
    # ============================================

    # --- Eigen Vermogen (Equity) ---
    # Use Closing Balance for all equity accounts
    # The "Resultaat" shown separately is computed from P&L but NOT added to total
    # (it's already reflected in equity account balances or will be at year close)

    # Main equity - Vrij besteedbaar eigen vermogen (0610)
    add_row(
        ref_code="VRIJ_EV",
        display_name="Vrij besteedbaar eigen vermogen",
        indent=0,
        formula='["account_number", "like", "061%"]',
        reverse_sign=True,
    )

    # Continuïteitsreserve (0605) - Note: named "Arbeid" in Excel but just "Continuïteitsreserve" in ERPNext
    add_row(
        ref_code="CONT_ARBEID",
        display_name="Continuïteitsreserve",
        indent=0,
        formula='["account_number", "=", "0605"]',
        reverse_sign=True,
    )

    # Continuïteitsreserve Productie (0606)
    add_row(
        ref_code="CONT_PROD",
        display_name="Continuïteitsreserve Productie",
        indent=0,
        formula='["account_number", "=", "0606"]',
        reverse_sign=True,
        hide_empty=True,
    )

    # Bestemmingsreserves (0608)
    add_row(
        ref_code="BESTEMMING",
        display_name="Bestemmingsreserves",
        indent=0,
        formula='["account_number", "like", "0608%"]',
        reverse_sign=True,
        hide_empty=True,
    )

    # Eindresultaat voorgaande jaren (9998) - accumulated retained earnings from prior years
    add_row(
        ref_code="EINDRESULTAAT",
        display_name="Eindresultaat voorgaande jaren",
        indent=0,
        formula='["account_number", "like", "9998%"]',
        reverse_sign=True,
        hide_empty=True,
    )

    # Resultaat lopend boekjaar (calculated from Income - Expense for current period)
    # This is for presentation - shows current year P&L separately
    add_row(
        ref_code="INCOME_TOTAL",
        display_name="",
        formula='["root_type", "=", "Income"]',
        balance_type="Period Movement (Debits - Credits)",
        hidden=True,
    )
    add_row(
        ref_code="EXPENSE_TOTAL",
        display_name="",
        formula='["root_type", "=", "Expense"]',
        balance_type="Period Movement (Debits - Credits)",
        hidden=True,
    )
    add_row(
        ref_code="RESULTAAT",
        display_name="Resultaat lopend boekjaar",
        indent=0,
        data_source="Calculated Amount",
        formula="-(INCOME_TOTAL + EXPENSE_TOTAL)",
        italic=True,
    )

    # Subtotal: Eigen vermogen
    # Include all equity accounts plus current year result
    add_row(
        ref_code="EIGEN_VERMOGEN",
        display_name="Eigen vermogen",
        indent=0,
        data_source="Calculated Amount",
        formula="VRIJ_EV + CONT_ARBEID + CONT_PROD + BESTEMMING + EINDRESULTAAT + RESULTAAT",
        bold=True,
    )

    add_blank()

    # --- Voorzieningen (Provisions) ---
    add_row(
        ref_code="VOORZIENINGEN",
        display_name="Voorzieningen",
        indent=0,
        formula='{"and": [["root_type", "=", "Liability"], ["account_type", "like", "%Provision%"]]}',
        reverse_sign=True,
        bold=True,
        hide_empty=True,
    )

    add_blank()

    # --- Langlopende schulden (Long-term Liabilities) ---
    add_row(
        ref_code="LANGLOPEND",
        display_name="Langlopende schulden",
        indent=0,
        formula='{"and": [["root_type", "=", "Liability"], ["account_name", "like", "%langlopend%"]]}',
        reverse_sign=True,
        bold=True,
        hide_empty=True,
    )

    add_blank()

    # --- Kortlopende schulden (Current Liabilities) ---

    # Reservering vakantiegeld (1710)
    add_row(
        ref_code="RES_VAK",
        display_name="Reservering vakantiegeld",
        indent=0,
        formula='["account_number", "=", "1710"]',
        reverse_sign=True,
    )

    # Belastingen & Sociale lasten (1720 + 1730)
    add_row(
        ref_code="BELASTING",
        display_name="Belastingen & Sociale lasten",
        indent=0,
        formula='{"or": [["account_number", "=", "1720"], ["account_number", "=", "1730"]]}',
        reverse_sign=True,
    )

    # Te betalen bedragen / Overige kortlopende schulden (1700)
    add_row(
        ref_code="TE_BETALEN",
        display_name="Overige kortlopende schulden",
        indent=0,
        formula='["account_number", "=", "1700"]',
        reverse_sign=True,
    )

    # Vooruitontvangen bedragen (1610 only - don't include 1710/1720 to avoid double counting)
    add_row(
        ref_code="VOORUIT_ONTV",
        display_name="Vooruitontvangen bedragen",
        indent=0,
        formula='["account_number", "=", "1610"]',
        reverse_sign=True,
        hide_empty=True,
    )

    # BTW schuld (1500-1540 liability accounts)
    add_row(
        ref_code="BTW_SCHULD",
        display_name="BTW schuld",
        indent=0,
        formula='{"and": [["root_type", "=", "Liability"], ["account_type", "=", "Tax"]]}',
        reverse_sign=True,
        hide_empty=True,
    )

    # Subtotal: Kortlopende schulden
    add_row(
        ref_code="KORTLOPEND",
        display_name="Kortlopende schulden",
        indent=0,
        data_source="Calculated Amount",
        formula="RES_VAK + BELASTING + TE_BETALEN + VOORUIT_ONTV + BTW_SCHULD",
        bold=True,
    )

    add_blank()

    # TOTAL LIABILITIES & EQUITY
    add_row(
        ref_code="TOTAAL_PASSIVA",
        display_name="Totaal passiva",
        indent=0,
        data_source="Calculated Amount",
        formula="EIGEN_VERMOGEN + VOORZIENINGEN + LANGLOPEND + KORTLOPEND",
        bold=True,
    )

    # Add all rows to template
    for row in rows:
        template.append("rows", row)

    template.insert()
    frappe.db.commit()

    print(f"Created Financial Report Template: {template.name}")
    print(f"Total rows: {len(rows)}")

    return template.name


if __name__ == "__main__":
    execute()
