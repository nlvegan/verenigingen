# ING Checkout Integratie Plan

**Datum**: 2026-01-05
**Status**: ✅ Voltooid (Fase 1-4)
**Prioriteit**: iDEAL eerst, daarna SDD
**Module**: `verenigingen/verenigingen_payments/ing_checkout/`

---

## 1. Achtergrond

### Context

ING Checkout is een samenwerking tussen ING en **Pay.nl**, gelanceerd in 2024. Pay.nl levert de technische infrastructuur (API, plugins, integraties), ING levert de bankrelatie en het merk.

Dit betekent dat de **Pay.nl API** de onderliggende technologie is voor ING Checkout.

### Huidige Situatie

- **Ponto**: Gebruikt voor banktransactie synchronisatie, maar SDD API endpoints zijn nog niet actief bij de banken
- **SEPA Bulk**: Handmatige upload van incassobatches via bankwebsite
- **Behoefte**:
  1. iDEAL betalingen voor eenmalige/adhoc contributies
  2. Enkelvoudige SDD requests via API (als aanvulling op bulk)

### Scope

| Prioriteit | Functionaliteit | Status |
|------------|-----------------|--------|
| 1 | iDEAL betalingen | Te implementeren |
| 2 | Enkelvoudige SDD via API | Te implementeren |
| - | Bulk SDD | Bestaande flow behouden (bankwebsite) |

---

## 2. Bronnen & Documentatie

### Primaire Bronnen

| Bron | URL | Inhoud |
|------|-----|--------|
| Pay.nl Developer Portal | https://developer.pay.nl/docs/platform | Volledige API documentatie |
| iDEAL Documentatie | https://developer.pay.nl/docs/ideal | iDEAL specifieke implementatie |
| SEPA Direct Debit | https://developer.pay.nl/docs/direct-debit-mandates | Incasso/mandaat API |
| Orders API | https://developer.pay.nl/docs/orders-1 | Order exchange formaat |
| PHP SDK (v3) | https://github.com/paynl/php-sdk | Nieuwste SDK |
| Legacy PHP SDK | https://github.com/paynl/sdk | Oudere SDK (rest-api) |

### ING Checkout Specifiek

| Bron | URL | Inhoud |
|------|-----|--------|
| ING Checkout Product | https://www.pay.nl/ing | Partnerschap pagina |
| ING Checkout Lancering | https://www.emerce.nl/nieuws/ing-pay-lanceren-ing-checkout-betaaldienst-webwinkels-meer-35-betaalopties | Nieuwsbericht 2024 |
| Banken.nl | https://www.banken.nl/nieuws/25602/ing-en-pay-lanceren-ing-checkout | Lanceringsdetails |
| ING SEPA Incasso | https://www.ing.nl/zakelijk/geld-ontvangen/ing-checkout/sepa-incasso | SDD via Checkout |

### Historische Context (Legacy - Niet Meer Actief)

De oude ING Kassa Compleet gebruikte **Ginger Payments** als backend:
- API endpoint was: `https://api.kassacompleet.nl/v1`
- Ginger PHP SDK: https://github.com/gingerpayments/ginger-php
- Kassa Compleet documentatie: https://silo.tips/download/kassa-compleet-api-documentation-v12

**Let op**: Kassa Compleet is vervangen door ING Checkout (Pay.nl platform).

---

## 3. API Architectuur

### Endpoints

| Component | URL | Doel | API Versie |
|-----------|-----|------|------------|
| **TGU** (Transacties) | `connect.pay.nl` | Order creatie, betalingen | V3 |
| **GMS** (Beheer) | `rest.pay.nl` | Refunds, rapportage, incasso | V2 |
| **Legacy** | `rest-api.pay.nl` | Oudere API versies | V12-V18 |

### Authenticatie

```
HTTP Basic Auth
Username: AT-####-#### (Token Code) OF SL-####-#### (Service ID)
Password: 40-character API token/secret
```

**Waar te vinden:**
- **Token Code + API Token**: Admin Panel → Merchant → Company Information
- **Service ID + Secret**: Admin Panel → Settings → Sales Locations

### ING Checkout Pakketten

| Pakket | Kosten | Features |
|--------|--------|----------|
| Basic | Gratis | Standaard betaalmethoden |
| Advanced | €19,90/maand | Direct debits, recurring payments, meerdere handelsnamen/locaties |

---

## 4. iDEAL Implementatie

### Payment Method ID

iDEAL = **10**

### Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Frappe    │────▶│   Pay.nl     │────▶│  iDEAL Bank │
│  (Order)    │     │  (Checkout)  │     │  (Betaling) │
└─────────────┘     └──────────────┘     └─────────────┘
       │                   │                    │
       │                   │◀───────────────────┘
       │                   │   (status update)
       │◀──────────────────┘
       │   (exchange webhook)
       ▼
┌─────────────┐
│  Verwerk    │
│  Betaling   │
└─────────────┘
```

### Order:Create Request

```json
POST https://connect.pay.nl/v3/orders
Authorization: Basic base64(AT-xxxx-xxxx:token)
Content-Type: application/json

{
  "serviceId": "SL-1234-1234",
  "amount": {
    "value": 2500,
    "currency": "EUR"
  },
  "description": "Contributie 2025",
  "reference": "MEM-2025-001",
  "returnUrl": "https://example.com/payment/complete",
  "exchangeUrl": "https://example.com/api/method/verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment",
  "paymentMethod": {
    "id": 10
  }
}
```

### Response

```json
{
  "id": "EX-1234-5678-9012",
  "status": "pending",
  "links": {
    "redirect": "https://connect.pay.nl/checkout/...",
    "status": "https://rest.pay.nl/v2/orders/EX-1234-5678-9012"
  }
}
```

### Exchange Webhook (Status Update)

```json
{
  "event": "status_changed",
  "type": "order",
  "version": "1",
  "id": "EX-1234-5678-9012",
  "object": {
    "id": "EX-1234-5678-9012",
    "reference": "MEM-2025-001",
    "status": {
      "code": 100,
      "action": "PAID"
    },
    "amount": {
      "value": 2500,
      "currency": "EUR"
    },
    "payments": [{
      "paymentMethod": {
        "id": 10,
        "name": "iDEAL"
      },
      "customerMethod": {
        "iban": "NL91INGB0001234567",
        "name": "J. de Vries",
        "bic": "INGBNL2A"
      }
    }]
  }
}
```

### Status Codes

| Code | Action | Betekenis |
|------|--------|-----------|
| 20 | PENDING | Wacht op betaling |
| 25 | PENDING | Betaling gestart |
| 100 | PAID | Betaald |
| -90 | CANCELLED | Geannuleerd |
| -63 | DENIED | Geweigerd |
| -64 | EXPIRED | Verlopen |

---

## 5. SEPA Direct Debit Implementatie

### Vereisten

- **Pay.nl pakket**: Minimaal "Professional (S)" of ING Checkout Advanced
- **Direct Debit feature** inschakelen in Admin Panel
- **Algemene Voorwaarden URL** vereist door SEPA regelgeving

### Standaard Limieten

| Limiet | Waarde | Aanpasbaar |
|--------|--------|------------|
| Mandaten per IBAN per dag | 1 | Ja, via Pay.nl |
| Max bedrag per incasso | €100 | Ja, via Pay.nl |
| Max totaal per 7 dagen | €10.000 | Ja, via Pay.nl |
| Mandaat geldigheid | 36 maanden | Nee (SEPA regel) |

### Mandaat Types

| Type | Gebruik | Automatisch |
|------|---------|-------------|
| **single** | Eenmalige incasso | Ja, na aanmaak |
| **recurring** | Periodiek vast interval | Ja, volgens schema |
| **flexible** | Variabele bedragen | Nee, handmatig triggeren |

### Stap 1: Mandaat Aanmaken

```json
POST https://rest.pay.nl/v2/directdebits/mandates
Authorization: Basic base64(AT-xxxx-xxxx:token)
Content-Type: application/json

{
  "serviceId": "SL-1234-1234",
  "type": "flexible",
  "amount": {
    "value": 2500,
    "currency": "EUR"
  },
  "description": "Contributie Vereniging",
  "debtor": {
    "iban": "NL91INGB0001234567",
    "name": "J. de Vries",
    "email": "j.devries@example.com"
  },
  "termsAndConditionsUrl": "https://example.com/voorwaarden",
  "exchangeUrl": "https://example.com/api/method/verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_mandate"
}
```

### Response

```json
{
  "mandateId": "IO-1234-5678-9012",
  "status": "pending",
  "objectCode": "IO-1234-5678-9012"
}
```

### Stap 2: Incasso Uitvoeren (Flexible Mandaat)

```json
POST https://rest.pay.nl/v2/directdebits
Authorization: Basic base64(AT-xxxx-xxxx:token)
Content-Type: application/json

{
  "mandateId": "IO-1234-5678-9012",
  "amount": {
    "value": 2500,
    "currency": "EUR"
  },
  "description": "Contributie Q1 2025",
  "processDate": "2025-01-15"
}
```

### Mandaat/Incasso Status Ophalen

```
GET https://rest.pay.nl/v2/directdebits/mandates/{mandateId}
GET https://rest.pay.nl/v2/directdebits/{referenceId}
```

---

## 6. Frappe Integratie Architectuur

### Directory Structuur

```
verenigingen/verenigingen_payments/
├── doctype/
│   ├── ing_checkout_settings/      # Singleton configuratie
│   ├── ing_checkout_transaction/   # Transactie log
│   ├── ing_checkout_mandate/       # SDD mandaten
│   ├── ponto_settings/             # Bestaand
│   └── ...
├── ing_checkout/
│   ├── __init__.py
│   ├── client.py                   # Pay.nl API client
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ideal_service.py        # iDEAL order creatie & verwerking
│   │   ├── mandate_service.py      # Mandaat lifecycle beheer
│   │   └── debit_service.py        # Incasso uitvoering
│   └── api/
│       ├── __init__.py
│       ├── webhook.py              # Exchange webhook handlers
│       └── payment.py              # Whitelisted payment endpoints
└── ponto/                          # Bestaand
```

### DocTypes

#### ING Checkout Settings (Single)

| Field | Type | Beschrijving |
|-------|------|--------------|
| `enabled` | Check | Integratie actief |
| `sandbox_mode` | Check | Test modus |
| `service_id` | Data | SL-xxxx-xxxx |
| `token_code` | Data | AT-xxxx-xxxx |
| `api_token` | Password | 40-char token |
| `default_return_url` | Data | Redirect na betaling |
| `webhook_url` | Read Only | Gegenereerde webhook URL |
| `terms_url` | Data | Algemene Voorwaarden URL (SDD) |

#### ING Checkout Transaction

| Field | Type | Beschrijving |
|-------|------|--------------|
| `transaction_id` | Data | EX-xxxx (Pay.nl ID) |
| `reference_doctype` | Link → DocType | Bv. Sales Invoice |
| `reference_name` | Dynamic Link | Document naam |
| `payment_method` | Select | ideal, direct-debit, etc. |
| `amount` | Currency | Bedrag |
| `status` | Select | pending, paid, cancelled, etc. |
| `customer_name` | Data | Naam van betaler |
| `customer_iban` | Data | IBAN van betaler |
| `raw_request` | JSON | Request payload |
| `raw_response` | JSON | Response/webhook data |

#### ING Checkout Mandate

| Field | Type | Beschrijving |
|-------|------|--------------|
| `mandate_id` | Data | IO-xxxx (Pay.nl ID) |
| `member` | Link → Member | Gekoppeld lid |
| `iban` | Data | Debiteur IBAN |
| `iban_holder` | Data | Tenaamstelling |
| `status` | Select | pending, active, cancelled |
| `type` | Select | single, recurring, flexible |
| `interval_period` | Select | week, month, quarter, year |
| `interval_quantity` | Int | Interval aantal |
| `next_debit_date` | Date | Volgende incasso |
| `amount` | Currency | Standaard bedrag |

### API Endpoints (Whitelisted)

```python
# Payment initiation
@frappe.whitelist()
def create_ideal_payment(reference_doctype, reference_name, amount, description):
    """Start iDEAL betaling voor document"""
    pass

@frappe.whitelist()
def get_payment_status(transaction_id):
    """Haal betaalstatus op"""
    pass

# Mandate management
@frappe.whitelist()
def create_mandate(member, iban, iban_holder, mandate_type="flexible"):
    """Maak nieuw SDD mandaat aan"""
    pass

@frappe.whitelist()
def execute_debit(mandate_id, amount, description, process_date=None):
    """Voer incasso uit op bestaand mandaat"""
    pass

# Webhooks (allow_guest=True)
@frappe.whitelist(allow_guest=True)
def handle_payment_webhook():
    """Verwerk Pay.nl exchange calls voor orders"""
    pass

@frappe.whitelist(allow_guest=True)
def handle_mandate_webhook():
    """Verwerk Pay.nl exchange calls voor mandaten/incasso's"""
    pass
```

---

## 7. Implementatie Roadmap

### Fase 1: Basis Infrastructuur

- [ ] ING Checkout Settings DocType
- [ ] API Client class met authenticatie
- [ ] Basis webhook endpoint
- [ ] Configuratie UI

### Fase 2: iDEAL Integratie

- [ ] ING Checkout Transaction DocType
- [ ] `ideal_service.py` - Order:Create implementatie
- [ ] Return URL handler (bedankpagina)
- [ ] Exchange webhook processing
- [ ] Status synchronisatie

### Fase 3: Sales Invoice Integratie

- [ ] "Betaal met iDEAL" knop op Sales Invoice
- [ ] Automatische Payment Entry bij succesvolle betaling
- [ ] Link naar ING Checkout Transaction
- [ ] Email notificatie bij betaling

### Fase 4: SEPA Direct Debit

- [ ] ING Checkout Mandate DocType
- [ ] `mandate_service.py` - Mandaat CRUD
- [ ] `debit_service.py` - Incasso uitvoering
- [ ] Mandate webhook handler
- [ ] Link met Member voor mandaatbeheer

### Fase 5: Member Portal (Optioneel)

- [ ] "Betaal openstaande facturen" in portal
- [ ] iDEAL payment flow vanuit portal
- [ ] Mandaat overzicht voor leden

### Fase 6: Productie & Monitoring

- [ ] Sandbox → Production switch
- [ ] Limiet verhogingen aanvragen
- [ ] Error handling & retry logica
- [ ] Monitoring dashboard
- [ ] Documentatie

---

## 8. Technische Overwegingen

### Webhook Beveiliging

Pay.nl ondersteunt signed webhooks. Implementeer validatie:

```python
def validate_webhook_signature(request):
    """Valideer Pay.nl webhook signature"""
    # TODO: Implementeer signature validatie
    # Zie: https://developer.pay.nl/docs/exchanges
    pass
```

### Idempotency

- Gebruik `reference` veld voor idempotente order creatie
- Check op bestaande transactie voordat nieuwe wordt aangemaakt
- Webhook handlers moeten idempotent zijn (dubbele calls negeren)

### Error Handling

```python
class INGCheckoutError(Exception):
    """Base exception voor ING Checkout integratie"""
    pass

class PaymentCreationError(INGCheckoutError):
    """Fout bij aanmaken betaling"""
    pass

class WebhookValidationError(INGCheckoutError):
    """Ongeldige webhook signature"""
    pass
```

### Retry Logica

Bij API failures:
- Max 3 retries met exponential backoff
- Log alle failures voor debugging
- Alert bij herhaalde failures

---

## 9. Migratie & Coëxistentie

### Bestaande SEPA Flow

De huidige bulk SEPA flow via bankwebsite blijft behouden:

| Aspect | Bulk SEPA (Bank) | ING Checkout SDD |
|--------|------------------|------------------|
| Volume | Hoog | Laag/Medium |
| Kosten | Bankkosten | Pay.nl fees |
| Mandaat beheer | Eigen administratie | Pay.nl beheert |
| PAIN.008 | Zelf genereren | Niet nodig |
| Use case | Kwartaalcontributies | Adhoc incasso's |

### Aanbevolen Strategie

1. **iDEAL**: Voor alle eenmalige betalingen en adhoc contributies
2. **Bulk SEPA**: Behouden voor periodieke bulk contributies
3. **ING Checkout SDD**: Voor enkelvoudige incasso's waar bulk niet praktisch is

---

## 10. Kosten Inschatting

### Pay.nl Transactiekosten (indicatief)

| Methode | Kosten per transactie |
|---------|----------------------|
| iDEAL | €0,29 |
| SEPA Direct Debit | €0,25 - €0,35 |

### ING Checkout Abonnement

| Pakket | Kosten |
|--------|--------|
| Basic | Gratis |
| Advanced (nodig voor SDD) | €19,90/maand |

---

## 11. Open Vragen

1. **Credentials**: Hebben we al ING Checkout credentials (test/productie)?
2. **Pakket**: Basic of Advanced nodig? (Advanced voor SDD)
3. **Limieten**: Moeten standaard limieten verhoogd worden?
4. **Portal**: Moet iDEAL betaling ook vanuit member portal mogelijk zijn?
5. **Reconciliatie**: Hoe integreren we met bestaande financiële rapportage?

---

## Changelog

| Datum | Wijziging |
|-------|-----------|
| 2026-01-05 | Initieel plan opgesteld |
| 2026-01-05 | Implementatie voltooid (Fase 1-4) |

---

## 12. Implementatie Resultaten

**Status**: ✅ Voltooid
**Commit**: `03afd024` - feat: add ING Checkout (Pay.nl) integration with security hardening

### Fase Status

| Fase | Beschrijving | Status |
|------|--------------|--------|
| 1 | Basis Infrastructuur | ✅ Voltooid |
| 2 | iDEAL Integratie | ✅ Voltooid |
| 3 | Sales Invoice Integratie | ✅ Voltooid |
| 4 | SEPA Direct Debit | ✅ Voltooid |
| 5 | Member Portal | ⏳ Optioneel - Niet geïmplementeerd |
| 6 | Productie & Monitoring | ⏳ Na go-live |

### Geïmplementeerde DocTypes

| DocType | Locatie | Beschrijving |
|---------|---------|--------------|
| ING Checkout Settings | `doctype/ing_checkout_settings/` | Singleton configuratie |
| ING Checkout Transaction | `doctype/ing_checkout_transaction/` | Transactie tracking |
| ING Checkout Mandate | `doctype/ing_checkout_mandate/` | SEPA mandaat beheer |

### Beveiligingsfeatures

| Feature | Implementatie |
|---------|---------------|
| IP Validatie | Pay.nl IP-lijst via `rest.pay.nl/v2/ipaddresses` (1-uur cache) |
| Signature Verificatie | HMAC-SHA256 als fallback (constant-time comparison) |
| Idempotency | Webhook Processing Log met hash-based duplicate detection |
| Atomiciteit | Database savepoints voor transactie/Payment Entry creatie |
| Bank Account | Alleen via `ing_checkout_bank_account` setting (geen fallbacks) |
| Audit Trail | Security justification comments op alle `ignore_permissions` |

### API Endpoints

| Endpoint | Type | Beschrijving |
|----------|------|--------------|
| `api.payment.create_payment` | Whitelisted | iDEAL betaling starten |
| `api.payment.get_payment_status` | Whitelisted | Status ophalen |
| `api.webhook.handle_payment` | Guest/Public | Payment webhook handler |
| `api.webhook.handle_mandate` | Guest/Public | Mandate webhook handler |
| `api.webhook.handle_direct_debit` | Guest/Public | Direct debit webhook handler |

### Settings Velden (Verenigingen Payments Settings)

| Veld | Type | Beschrijving |
|------|------|--------------|
| `ing_checkout_enabled` | Check | Integratie actief |
| `ing_checkout_sandbox_mode` | Check | Test modus |
| `ing_checkout_service_id` | Data | SL-xxxx-xxxx |
| `ing_checkout_token_code` | Data | AT-xxxx-xxxx |
| `ing_checkout_api_token` | Password | API token |
| `ing_checkout_bank_account` | Link | Bank rekening voor Payment Entry |
| `ing_checkout_webhook_secret` | Password | HMAC verificatie secret |

### Test Coverage

```
✅ 24 tests passing
├── 10 API tests (api/test_*.py)
└── 14 client tests (test_client.py)
```

### Volgende Stappen

1. **Productie Credentials**: ING Checkout account aanvragen
2. **Limiet Verhogingen**: Indien nodig via Pay.nl admin panel
3. **Member Portal**: Optionele iDEAL betaling vanuit portal
4. **Monitoring Dashboard**: Error tracking en rapportage
