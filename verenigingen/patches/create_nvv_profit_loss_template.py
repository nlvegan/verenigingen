"""
Create NVV Profit & Loss Financial Report Template

This patch creates a P&L template matching the NVV Jaarrekening structure.
Can be run via: bench --site veg11.veganisme.org execute verenigingen.patches.create_nvv_profit_loss_template.execute
"""

import frappe


def execute():
    """Create the NVV Profit & Loss Financial Report Template."""
    if frappe.db.exists("Financial Report Template", "NVV Winst & Verlies"):
        frappe.delete_doc("Financial Report Template", "NVV Winst & Verlies", force=True)
        print("Deleted existing template")

    template = frappe.new_doc("Financial Report Template")
    template.template_name = "NVV Winst & Verlies"
    template.report_type = "Profit and Loss Statement"
    template.disabled = 0

    # Build the rows
    rows = []
    idx = 1

    def add_row(
        ref_code="",
        display_name="",
        indent=0,
        data_source="Account Data",
        balance_type="Period Movement (Debits - Credits)",
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
    # BATEN (Income)
    # ============================================
    # Note: Income accounts have credit balances, so debit-credit gives negative
    # We use reverse_sign=True to show positive values for income

    # --- Contributie & Abonnementen ---
    add_row(
        ref_code="CONTRIBUTIE",
        display_name="Contributie en abonnementen",
        indent=0,
        formula='["account_number", "=", "8000"]',
        reverse_sign=True,
    )

    # --- Donaties ---
    add_row(
        ref_code="DON_DIRECT",
        display_name="Donaties - direct",
        indent=1,
        formula='["account_number", "=", "8010"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="DON_DIGITAL",
        display_name="Donaties - digitale platforms",
        indent=1,
        formula='["account_number", "=", "8015"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="DON_NALAT",
        display_name="Donaties - nalatenschappen",
        indent=1,
        formula='["account_number", "=", "8020"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="DON_CAMPAGNE",
        display_name="Donaties - campagnes",
        indent=1,
        formula='["account_number", "=", "8025"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="DONATIES",
        display_name="Donaties",
        indent=0,
        data_source="Calculated Amount",
        formula="DON_DIRECT + DON_DIGITAL + DON_NALAT + DON_CAMPAGNE",
        bold=True,
    )

    # --- Advertenties ---
    add_row(
        ref_code="ADV_VM",
        display_name="Advertenties Vegan Magazine",
        indent=1,
        formula='["account_number", "=", "8030"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="ADV_VCVF",
        display_name="Advertenties VC/VF",
        indent=1,
        formula='["account_number", "=", "8035"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="ADVERTENTIES",
        display_name="Advertenties",
        indent=0,
        data_source="Calculated Amount",
        formula="ADV_VM + ADV_VCVF",
        bold=True,
        hide_empty=True,
    )

    # --- Verkoop ---
    add_row(
        ref_code="VERKOOP_WEBSHOP",
        display_name="Verkoop webshop",
        indent=1,
        formula='["account_number", "=", "8040"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="VERKOOP_STANDS",
        display_name="Verkoop en donaties via stands",
        indent=1,
        formula='["account_number", "=", "8045"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="VERKOOP",
        display_name="Verkoop",
        indent=0,
        data_source="Calculated Amount",
        formula="VERKOOP_WEBSHOP + VERKOOP_STANDS",
        bold=True,
        hide_empty=True,
    )

    # --- Commissies ---
    add_row(
        ref_code="COMM_KEURMERK",
        display_name="Commissie Vegan Keurmerk",
        indent=1,
        formula='["account_number", "=", "8050"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="COMM_SPREADSHIRT",
        display_name="Commissie Spreadshirt",
        indent=1,
        formula='["account_number", "=", "8055"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="COMM_MJKZ",
        display_name="Provisie MJKZ-verkoop",
        indent=1,
        formula='["account_number", "=", "8056"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="COMMISSIES",
        display_name="Commissies",
        indent=0,
        data_source="Calculated Amount",
        formula="COMM_KEURMERK + COMM_SPREADSHIRT + COMM_MJKZ",
        bold=True,
        hide_empty=True,
    )

    # --- Fondsen & Subsidies ---
    add_row(
        ref_code="FONDSEN",
        display_name="Fondsen en subsidies",
        indent=0,
        formula='["account_number", "=", "8060"]',
        reverse_sign=True,
        hide_empty=True,
    )

    # --- Overige baten ---
    add_row(
        ref_code="BATEN_PROMOTIE",
        display_name="Promotie inkomsten",
        indent=1,
        formula='["account_number", "=", "8070"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="BATEN_EDUCATIE",
        display_name="Bijdrage scholen educatie",
        indent=1,
        formula='["account_number", "=", "8075"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="BATEN_TICKETS",
        display_name="Verkoop tickets evenementen",
        indent=1,
        formula='["account_number", "=", "8080"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="BATEN_BIJEENK",
        display_name="Deelnemersbijdragen bijeenkomsten",
        indent=1,
        formula='["account_number", "=", "5250"]',
        reverse_sign=True,
        hide_empty=True,
    )
    add_row(
        ref_code="OVERIGE_BATEN",
        display_name="Overige baten",
        indent=0,
        data_source="Calculated Amount",
        formula="BATEN_PROMOTIE + BATEN_EDUCATIE + BATEN_TICKETS + BATEN_BIJEENK",
        bold=True,
        hide_empty=True,
    )

    add_blank()

    # TOTAAL BATEN
    add_row(
        ref_code="TOTAAL_BATEN",
        display_name="Totaal baten",
        indent=0,
        data_source="Calculated Amount",
        formula="CONTRIBUTIE + DONATIES + ADVERTENTIES + VERKOOP + COMMISSIES + FONDSEN + OVERIGE_BATEN",
        bold=True,
    )

    add_blank()

    # ============================================
    # LASTEN (Expenses)
    # ============================================
    # Note: Expense accounts have debit balances, so debit-credit gives positive
    # We show expenses as positive (which they naturally are in debit-credit)

    # --- Personeelskosten ---
    add_row(
        ref_code="LONEN",
        display_name="Lonen en salarissen",
        indent=1,
        formula='["account_number", "=", "4000"]',
        hide_empty=True,
    )
    add_row(
        ref_code="SOC_LASTEN",
        display_name="Sociale lasten",
        indent=1,
        formula='["account_number", "=", "4030"]',
        hide_empty=True,
    )
    add_row(
        ref_code="REIS_PERS",
        display_name="Reiskosten medewerkers",
        indent=1,
        formula='["account_number", "=", "4040"]',
        hide_empty=True,
    )
    add_row(
        ref_code="RES_VAKGELD",
        display_name="Reservering vakantiegeld",
        indent=1,
        formula='{"or": [["account_number", "=", "4070"], ["account_number", "=", "4071"]]}',
        hide_empty=True,
    )
    add_row(
        ref_code="OV_PERS",
        display_name="Overige personeelskosten",
        indent=1,
        formula='["account_number", "=", "4022"]',
        hide_empty=True,
    )
    add_row(
        ref_code="PERSONEELSKOSTEN",
        display_name="Personeelskosten",
        indent=0,
        data_source="Calculated Amount",
        formula="LONEN + SOC_LASTEN + REIS_PERS + RES_VAKGELD + OV_PERS",
        bold=True,
    )

    # --- Bestuurskosten ---
    add_row(
        ref_code="BESTUURSKOSTEN",
        display_name="Bestuurskosten",
        indent=0,
        formula='{"and": [["account_number", ">=", "4075"], ["account_number", "<=", "4100"]]}',
        hide_empty=True,
    )

    # --- Kantoor & Administratie ---
    add_row(
        ref_code="LEDENSERVICE",
        display_name="Ledenservice",
        indent=1,
        formula='{"or": [["account_number", "=", "4300"], ["account_number", "=", "4305"]]}',
        hide_empty=True,
    )
    add_row(
        ref_code="KANTOOR_MAT",
        display_name="Kantoorkosten",
        indent=1,
        formula='{"and": [["account_number", ">=", "4310"], ["account_number", "<=", "4340"]]}',
        hide_empty=True,
    )
    add_row(
        ref_code="ADMIN_KOSTEN",
        display_name="Administratiekosten",
        indent=1,
        formula='{"and": [["account_number", ">=", "4500"], ["account_number", "<=", "4690"]]}',
        hide_empty=True,
    )
    add_row(
        ref_code="RENTEBATEN",
        display_name="Rentebaten",
        indent=1,
        formula='["account_number", "=", "4720"]',
        hide_empty=True,
    )
    add_row(
        ref_code="KANTOOR_ADMIN",
        display_name="Kantoor en administratie",
        indent=0,
        data_source="Calculated Amount",
        formula="LEDENSERVICE + KANTOOR_MAT + ADMIN_KOSTEN + RENTEBATEN",
        bold=True,
    )

    # --- Afschrijvingen ---
    add_row(
        ref_code="AFSCHRIJVINGEN",
        display_name="Afschrijvingen",
        indent=0,
        formula='{"and": [["account_number", ">=", "4800"], ["account_number", "<=", "4820"]]}',
        hide_empty=True,
    )

    add_blank()

    # --- Activiteitenkosten (5000-5900 range) ---
    # ALV
    add_row(
        ref_code="ALV_KOSTEN",
        display_name="ALV",
        indent=1,
        formula='{"and": [["account_number", ">=", "5000"], ["account_number", "<=", "5006"]]}',
        hide_empty=True,
    )

    # Vrijwilligers & Interne evenementen
    add_row(
        ref_code="VRIJWILLIGERS",
        display_name="Vrijwilligers & interne evenementen",
        indent=1,
        formula='{"and": [["account_number", ">=", "5010"], ["account_number", "<=", "5090"]]}',
        hide_empty=True,
    )

    # IT & Websites
    add_row(
        ref_code="IT_WEBSITES",
        display_name="IT en websites",
        indent=1,
        formula='{"and": [["account_number", ">=", "5100"], ["account_number", "<=", "5160"]]}',
        hide_empty=True,
    )

    # Vegan Awards
    add_row(
        ref_code="VEGAN_AWARDS",
        display_name="Vegan Awards",
        indent=1,
        formula='{"and": [["account_number", ">=", "5200"], ["account_number", "<=", "5209"]]}',
        hide_empty=True,
    )

    # NLVegan Fair
    add_row(
        ref_code="NLVEGAN_FAIR",
        display_name="NLVegan Fair",
        indent=1,
        formula='{"and": [["account_number", ">=", "5210"], ["account_number", "<=", "5216"]]}',
        hide_empty=True,
    )

    # Andere evenementen (Kaasmarkt, Potlucks, Bijeenkomsten)
    # Note: Excludes 5250 which is income (deelnemersbijdragen)
    add_row(
        ref_code="ANDERE_EVENTS",
        display_name="Andere evenementen",
        indent=1,
        formula='{"and": [["account_number", ">=", "5220"], ["account_number", "<", "5250"]]}',
        hide_empty=True,
    )

    # Stands & Spreken
    add_row(
        ref_code="STANDS_SPREKEN",
        display_name="Stands en spreken",
        indent=1,
        formula='{"and": [["account_number", ">=", "5270"], ["account_number", "<=", "5279"]]}',
        hide_empty=True,
    )

    # Vegan Magazine
    add_row(
        ref_code="VEGAN_MAGAZINE",
        display_name="Vegan Magazine",
        indent=1,
        formula='{"and": [["account_number", ">=", "5300"], ["account_number", "<=", "5330"]]}',
        hide_empty=True,
    )

    # Content (Recepten, Wiki, Educatie)
    add_row(
        ref_code="CONTENT",
        display_name="Content (recepten, wiki, educatie)",
        indent=1,
        formula='{"and": [["account_number", ">=", "5340"], ["account_number", "<=", "5370"]]}',
        hide_empty=True,
    )

    # Promotie & Campagnes
    add_row(
        ref_code="PROMOTIE_CAMP",
        display_name="Promotie en campagnes",
        indent=1,
        formula='{"and": [["account_number", ">=", "5400"], ["account_number", "<=", "5446"]]}',
        hide_empty=True,
    )

    # VeganChallenge
    add_row(
        ref_code="VEGANCHALLENGE",
        display_name="VeganChallenge",
        indent=1,
        formula='{"and": [["account_number", ">=", "5501"], ["account_number", "<=", "5510"]]}',
        hide_empty=True,
    )

    # Melk Je Kan Zonder
    add_row(
        ref_code="MJKZ",
        display_name="Melk Je Kan Zonder",
        indent=1,
        formula='{"and": [["account_number", ">=", "5640"], ["account_number", "<=", "5647"]]}',
        hide_empty=True,
    )

    # Projecten
    add_row(
        ref_code="PROJECTEN",
        display_name="Projecten",
        indent=1,
        formula='{"and": [["account_number", ">=", "5660"], ["account_number", "<=", "5700"]]}',
        hide_empty=True,
    )

    # Lidmaatschappen & Donaties
    add_row(
        ref_code="LIDM_DON",
        display_name="Lidmaatschappen en donaties",
        indent=1,
        formula='{"and": [["account_number", ">=", "5895"], ["account_number", "<=", "5910"]]}',
        hide_empty=True,
    )

    # Subtotal: Activiteiten
    add_row(
        ref_code="ACTIVITEITEN",
        display_name="Activiteiten",
        indent=0,
        data_source="Calculated Amount",
        formula="ALV_KOSTEN + VRIJWILLIGERS + IT_WEBSITES + VEGAN_AWARDS + NLVEGAN_FAIR + ANDERE_EVENTS + STANDS_SPREKEN + VEGAN_MAGAZINE + CONTENT + PROMOTIE_CAMP + VEGANCHALLENGE + MJKZ + PROJECTEN + LIDM_DON",
        bold=True,
    )

    # --- Inkoop ---
    add_row(
        ref_code="INKOOP",
        display_name="Inkoop materiaal webshop",
        indent=0,
        formula='["account_number", "=", "7000"]',
        hide_empty=True,
    )

    add_blank()

    # TOTAAL LASTEN
    add_row(
        ref_code="TOTAAL_LASTEN",
        display_name="Totaal lasten",
        indent=0,
        data_source="Calculated Amount",
        formula="PERSONEELSKOSTEN + BESTUURSKOSTEN + KANTOOR_ADMIN + AFSCHRIJVINGEN + ACTIVITEITEN + INKOOP",
        bold=True,
    )

    add_blank()

    # ============================================
    # RESULTAAT
    # ============================================
    add_row(
        ref_code="RESULTAAT",
        display_name="Resultaat",
        indent=0,
        data_source="Calculated Amount",
        formula="TOTAAL_BATEN - TOTAAL_LASTEN",
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
