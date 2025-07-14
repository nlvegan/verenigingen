# E-Boekhouden to ERPNext field mapping configuration
# This module provides comprehensive field mappings for proper data import

# Basic invoice field mappings
INVOICE_FIELD_MAP = {
    # Basic fields
    "date": "posting_date",
    "invoiceNumber": "custom_eboekhouden_invoice_number",
    "description": "remarks",
    "Referentie": "po_no",  # Customer reference
    "Betalingstermijn": "payment_days",  # For calculating due_date
    # Fields requiring processing
    "relationId": "party_lookup",  # Needs party resolution
    "amount": "total_amount",  # Needs sign handling for returns
    "id": "custom_eboekhouden_mutation_nr",  # Mutation tracking
}

# BTW (VAT) Code mapping for Dutch tax system
BTW_CODE_MAP = {
    "HOOG_VERK_21": {
        "rate": 21,
        "type": "Output VAT",
        "account_name": "1500 - BTW af te dragen 21% - NVV",
        "account_fallback": "VAT 21% - TC",
        "description": "Hoge BTW verkoop 21%",
    },
    "LAAG_VERK_9": {
        "rate": 9,
        "type": "Output VAT",
        "account_name": "1520 - BTW af te dragen overig - NVV",
        "account_fallback": "VAT 6% - TC",
        "description": "Lage BTW verkoop 9%",
    },
    "HOOG_INK_21": {
        "rate": 21,
        "type": "Input VAT",
        "account_name": "1530 - BTW te vorderen - NVV",
        "account_fallback": "VAT 21% - TC",
        "description": "Hoge BTW inkoop 21%",
    },
    "LAAG_INK_9": {
        "rate": 9,
        "type": "Input VAT",
        "account_name": "1530 - BTW te vorderen - NVV",
        "account_fallback": "VAT 6% - TC",
        "description": "Lage BTW inkoop 9%",
    },
    "HOOG_VERK_6": {
        "rate": 6,
        "type": "Output VAT",
        "account_name": "1510 - BTW af te dragen 6% - NVV",
        "account_fallback": "VAT 6% - TC",
        "description": "BTW verkoop 6%",
    },
    "LAAG_INK_6": {
        "rate": 6,
        "type": "Input VAT",
        "account_name": "1530 - BTW te vorderen - NVV",
        "account_fallback": "VAT 6% - TC",
        "description": "BTW inkoop 6%",
    },
    "VERLEGDE_BTW": {
        "rate": 21,
        "type": "Reverse Charge",
        "account_name": "1540 - BTW R/C - NVV",
        "account_fallback": "VAT 21% - TC",
        "description": "Verlegde BTW",
    },
    "GEEN": {
        "rate": 0,
        "type": None,
        "account_name": None,
        "account_fallback": None,
        "description": "Geen BTW",
    },
    "VRIJ": {
        "rate": 0,
        "type": None,
        "account_name": None,
        "account_fallback": None,
        "description": "BTW vrijgesteld",
    },
}

# Line item field mappings (Regels)
LINE_ITEM_FIELD_MAP = {
    "Omschrijving": "description",
    "Aantal": "qty",
    "Prijs": "rate",
    "Eenheid": "uom",
    "BTWCode": "btw_code",
    "GrootboekNummer": "gl_account_code",
    "KostenplaatsId": "cost_center_id",
}

# Unit of measure mappings
UOM_MAP = {
    "Stk": "Nos",
    "Stuks": "Nos",
    "St": "Nos",
    "Nos": "Nos",
    "Uur": "Hour",
    "Uren": "Hour",
    "Dag": "Day",
    "Dagen": "Day",
    "Maand": "Month",
    "Maanden": "Month",
    "Jaar": "Year",
    "kg": "Kg",
    "gram": "Gram",
    "liter": "Litre",
    "m": "Meter",
    "cm": "Cm",
    "mm": "mm",
    "m2": "Sq Meter",
    "m3": "Cubic Meter",
    "%": "Percent",
}

# Default payment terms in days for common Dutch business practices
DEFAULT_PAYMENT_TERMS = {
    7: "Netto 7 dagen",
    14: "Netto 14 dagen",
    21: "Netto 21 dagen",
    30: "Netto 30 dagen",
    45: "Netto 45 dagen",
    60: "Netto 60 dagen",
    90: "Netto 90 dagen",
}

# Account type mapping for automatic GL account assignment (based on NVV's actual CoA)
ACCOUNT_TYPE_MAP = {
    # Income accounts (80000-89999)
    "income": {
        "range_start": 80000,
        "range_end": 89999,
        "default_account": "80001 - Contributie Leden plus Abonnementen - NVV",
        "account_type": "Income Account",
    },
    # Expense accounts (40000-49999)
    "expense": {
        "range_start": 40000,
        "range_end": 49999,
        "default_account": "44009 - Onvoorziene kosten - NVV",
        "account_type": "Expense Account",
    },
    # Asset accounts (10000-19999)
    "asset": {
        "range_start": 10000,
        "range_end": 19999,
        "default_account": "13900 - Debiteuren handelsvorderingen - NVV",
        "account_type": "Receivable",
    },
    # Liability accounts (14000-19999) - overlaps with assets in NVV's system
    "liability": {
        "range_start": 14000,
        "range_end": 19999,
        "default_account": "14700 - Crediteuren handelsschulden - NVV",
        "account_type": "Payable",
    },
}

# Enhanced Item group determination based on description keywords
ITEM_GROUP_KEYWORDS = {
    "service": [
        "dienst",
        "service",
        "advies",
        "consultancy",
        "training",
        "onderhoud",
        "reparatie",
        "support",
        "hulp",
        "begeleiding",
        "coaching",
        "cursus",
        "workshop",
        "seminar",
        "administratie",
        "boekhouding",
        "belasting",
        "juridisch",
        "notaris",
        "advocaat",
        "ondersteuning",
        "maintenance",
        "consultatie",
    ],
    "product": [
        "product",
        "goed",
        "materiaal",
        "software",
        "licentie",
        "hardware",
        "computer",
        "laptop",
        "tablet",
        "telefoon",
        "scanner",
        "apparaat",
        "meubilair",
        "bureau",
        "stoel",
        "kast",
        "lamp",
        "equipment",
        "toestel",
        "machine",
        "gereedschap",
        "voorraad",
        "inventaris",
    ],
    "travel": [
        "reis",
        "transport",
        "parkeren",
        "benzine",
        "diesel",
        "kilometergeld",
        "vliegtuig",
        "trein",
        "bus",
        "taxi",
        "hotel",
        "verblijf",
        "accommodatie",
        "maaltijd",
        "lunch",
        "diner",
        "ontbijt",
        "catering",
        "restaurant",
        "vliegticket",
        "reiskosten",
        "km-vergoeding",
    ],
    "marketing": [
        "marketing",
        "reclame",
        "advertentie",
        "promotie",
        "website",
        "drukwerk",
        "flyer",
        "brochure",
        "poster",
        "banner",
        "logo",
        "huisstijl",
        "design",
        "fotografie",
        "video",
        "social media",
        "seo",
        "google",
        "facebook",
        "instagram",
        "linkedin",
        "reclamekosten",
        "campagne",
    ],
    "utility": [
        "elektra",
        "gas",
        "water",
        "internet",
        "telefoon",
        "mobiel",
        "hosting",
        "domain",
        "email",
        "cloud",
        "backup",
        "security",
        "verzekering",
        "energie",
        "verwarming",
        "airco",
        "schoonmaak",
        "glasvezel",
        "telecom",
        "provider",
        "nutsvoorziening",
    ],
    "office": [
        "kantoorartikelen",
        "kantoorbenodigdheden",
        "kantoor artikelen",
        "bureau-artikelen",
        "bureau artikelen",
        "papier",
        "pen",
        "potlood",
        "nietmachine",
        "paperclip",
        "paperclips",
        "map",
        "dossier",
        "archief",
        "printer",
        "inkt",
        "toner",
        "cartridge",
        "post",
        "porto",
        "verzending",
        "envelop",
        "pakket",
        "stationary",
        "briefpapier",
        "kantoor",
    ],
    "subscription": [
        "abonnement",
        "subscription",
        "maandelijks",
        "jaarlijks",
        "licentie",
        "microsoft",
        "office",
        "adobe",
        "zoom",
        "slack",
        "dropbox",
        "mailchimp",
        "saas",
        "platform",
        "tool",
        "applicatie",
        "lidmaatschap",
        "membership",
        "recurring",
        "periodiek",
        "software-licentie",
    ],
    "finance": [
        "bank",
        "rente",
        "kosten",
        "administratiekosten",
        "transactiekosten",
        "creditcard",
        "paypal",
        "mollie",
        "stripe",
        "iDEAL",
        "factoring",
        "financiering",
        "lening",
        "hypotheek",
        "verzekering",
        "premie",
        "bankkosten",
        "krediet",
        "financi",
    ],
    "catering": [
        "catering",
        "lunch",
        "diner",
        "ontbijt",
        "koffie",
        "thee",
        "maaltijd",
        "consumptie",
        "drankje",
        "restaurant",
        "horeca",
        "eten",
        "drinken",
        "buffet",
        "borrel",
        "receptie",
        "meeting-lunch",
        "vergaderservice",
    ],
}

# Enhanced Default item groups for fallback with proper ERPNext mapping
DEFAULT_ITEM_GROUPS = {
    "default": "Services",
    "service": "Services",
    "product": "Products",
    "travel": "Travel and Expenses",
    "marketing": "Marketing and Advertising",
    "utility": "Utilities and Infrastructure",
    "office": "Office Supplies",
    "subscription": "Software and Subscriptions",
    "finance": "Financial Services",
    "catering": "Catering and Events",
    "sales": "Services",  # Backward compatibility
    "purchase": "Products",  # Backward compatibility
}

# Item categorization by price ranges (EUR) for smart item type detection
PRICE_CATEGORY_RANGES = {
    "consumable": (0, 50),  # Office supplies, small items
    "equipment": (50, 1000),  # Furniture, electronics
    "investment": (1000, 99999),  # Major purchases, vehicles
}

# VAT-based categorization hints for item group determination
VAT_CATEGORY_HINTS = {
    "GEEN": "service",  # Exempt services often professional services
    "VRIJ": "service",  # Zero-rated services
    "LAAG_VERK_6": "utility",  # 6% VAT often utilities, books
    "LAAG_VERK_9": "product",  # 9% VAT certain products
    "HOOG_VERK_21": "product",  # 21% VAT general products/services
}

# Account code based item hints (based on NVV's actual chart of accounts)
ACCOUNT_CODE_ITEM_HINTS = {
    # 40000-44999: General expenses -> Services/Products mixed
    (40000, 42999): "service",
    (43000, 43999): "product",
    (44000, 44999): "service",
    # 45000-49999: Other operational expenses
    (45000, 45999): "utility",
    (46000, 46999): "office",
    (47000, 47999): "marketing",
    (48000, 48999): "finance",
    (49000, 49999): "service",
    # 80000-89999: Revenue -> Services (default for sales)
    (80000, 89999): "service",
}
