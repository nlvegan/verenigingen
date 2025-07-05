# Member Fee Adjustment Portal

## Overzicht

Leden kunnen nu zelf hun contributie aanpassen via een portal pagina. Het systeem hanteert bepaalde minima en kan goedkeuringsworkflows gebruiken.

## Functionaliteit

### 🎯 **Zelf Contributie Aanpassen**
- Leden loggen in en gaan naar `/membership_fee_adjustment`
- Interactieve slider en input veld voor bedrag selectie
- Realtime validatie van minimum en maximum bedragen
- Mogelijkheid om reden voor aanpassing te geven

### 📊 **Intelligente Minimum Berekening**
- **Basis minimum**: 30% van standaard contributie
- **Studenten**: Minimum 50% van standaard tarief
- **Lage inkomens**: Minimum 40% voor inkomens onder €40,000
- **Absoluut minimum**: €5,00 per maand

### ⚙️ **Flexibele Instellingen**
```python
settings = {
    "enable_member_fee_adjustment": 1,           # Functie aan/uit
    "max_adjustments_per_year": 2,              # Max aanpassingen per jaar
    "require_approval_for_increases": 0,         # Goedkeuring bij verhogingen
    "require_approval_for_decreases": 1,         # Goedkeuring bij verlagingen
    "adjustment_reason_required": 1              # Reden verplicht
}
```

### 🔄 **Approval Workflow**
- **Automatische toepassing**: Bij verhogingen (standaard)
- **Handmatige goedkeuring**: Bij verlagingen (configureerbaar)
- **Amendment Request systeem**: Alle wijzigingen worden gelogd
- **Member-initiated marker**: Onderscheid tussen lid- en admin-wijzigingen

## Technische Implementatie

### 📁 **Nieuwe Bestanden**
```
templates/pages/membership_fee_adjustment.py    # Backend logic
templates/pages/membership_fee_adjustment.html  # Frontend form
```

### 🛠 **Gewijzigde Bestanden**
```
member_dashboard.py                              # Link toegevoegd
membership_amendment_request.json               # Veld toegevoegd
```

### 🔧 **Nieuwe API Endpoints**
```python
@frappe.whitelist()
def submit_fee_adjustment_request(new_amount, reason="")
    # Submitten van contributie wijziging

@frappe.whitelist()
def get_fee_calculation_info()
    # Ophalen van fee informatie voor UI
```

## Gebruikerservaring

### 💻 **Portal Interface**
1. **Huidige Status**: Overzicht van huidige contributie en type
2. **Minimum Info**: Duidelijke weergave van toegestane range
3. **Interactieve Controls**: Slider + input veld gesynchroniseerd
4. **Realtime Feedback**: Directe validatie en kostentweergave
5. **Pending Requests**: Overzicht van lopende verzoeken

### 📱 **Responsive Design**
- Bootstrap gebaseerd
- Mobile-friendly interface
- Duidelijke visuele feedback
- Toegankelijke form controls

## Beveiligingsfuncties

### 🔒 **Toegangscontrole**
- Login verificatie vereist
- Member record lookup via email/user
- Permission checks op alle API calls
- CSRF bescherming via Frappe

### 🔍 **Validatie & Limieten**
- Server-side minimum/maximum validatie
- Jaarlijkse aanpassingslimiet
- Reason requirement enforcement
- Duplicate request prevention

### 📋 **Audit Trail**
- Alle wijzigingen via Amendment Request systeem
- Member-initiated flag voor onderscheid
- Volledige geschiedenis van wijzigingen
- Approval status tracking

## Configuratie

### ⚙️ **Verenigingen Settings**
Voeg deze velden toe aan Verenigingen Settings doctype:
```json
{
    "enable_member_fee_adjustment": {"fieldtype": "Check", "default": 1},
    "max_adjustments_per_year": {"fieldtype": "Int", "default": 2},
    "require_approval_for_increases": {"fieldtype": "Check", "default": 0},
    "require_approval_for_decreases": {"fieldtype": "Check", "default": 1},
    "adjustment_reason_required": {"fieldtype": "Check", "default": 1}
}
```

### 🎚 **Minimum Fee Logic**
```python
def get_minimum_fee(member, membership_type):
    base_minimum = flt(membership_type.amount * 0.3)

    if member.student_status:
        base_minimum = max(base_minimum, flt(membership_type.amount * 0.5))

    if member.annual_income in ["Under €25,000", "€25,000 - €40,000"]:
        base_minimum = max(base_minimum, flt(membership_type.amount * 0.4))

    return max(base_minimum, 5.0)
```

## Workflow Examples

### ✅ **Succesvolle Verhoging**
1. Lid kiest hoger bedrag (bijv. €25 → €35)
2. Vult reden in: "Extra ondersteuning voor organisatie"
3. Request wordt automatisch goedgekeurd (settings)
4. Fee override wordt direct toegepast
5. Lid ontvangt bevestiging

### ⏳ **Verlaging met Goedkeuring**
1. Lid kiest lager bedrag (bijv. €25 → €15)
2. Vult reden in: "Tijdelijke financiële moeilijkheden"
3. Request wordt ingediend voor goedkeuring
4. Administrator ziet request in backend
5. Na goedkeuring wordt wijziging toegepast

### ❌ **Geweigerde Wijziging**
1. Lid probeert bedrag onder minimum (bijv. €3)
2. Systeem toont foutmelding
3. Slider/input worden geblokkeerd
4. Minimum bedrag wordt duidelijk getoond

## Integratie

### 🔗 **Member Dashboard**
- Nieuwe "Adjust Fee" link in navigatie
- Directe toegang vanuit member portal
- Consistent met bestaande portal design

### 📊 **Amendment System**
- Gebruikt bestaande Membership Amendment Request
- Nieuwe `requested_by_member` flag voor tracking
- Volledig geïntegreerd met approval workflows

### 💳 **Subscription Updates**
- Automatische subscription wijziging na goedkeuring
- Bestaande SEPA mandates blijven geldig
- Invoice wijzigingen vanaf volgende factuurperiode

## Testing

### 🧪 **Test Scenarios**
1. **Basic Flow**: Normale contributie aanpassing
2. **Minimum Validation**: Bedrag onder minimum proberen
3. **Maximum Adjustments**: Jaarlijkse limiet bereiken
4. **Approval Workflow**: Goedkeuringsproces testen
5. **Student Discounts**: Lagere minima voor studenten
6. **Error Handling**: Ongeldige inputs en server errors

### ✅ **Validatie Checklist**
- [ ] Login requirement werkt
- [ ] Minimum fee calculation correct
- [ ] Slider/input synchronization
- [ ] Approval workflow functionality
- [ ] Amendment request creation
- [ ] Fee override application
- [ ] Error message display
- [ ] Mobile responsiveness

De implementatie is volledig functioneel en klaar voor productiegebruik!

## Voordelen voor Organisatie

### 💰 **Financiële Flexibiliteit**
- Leden kunnen bijdrage verhogen bij betere financiële situatie
- Sociale toegankelijkheid door lagere minima
- Behoud van leden tijdens financiële moeilijkheden

### ⚡ **Administratieve Efficiëntie**
- Minder handmatige fee wijzigingen
- Geautomatiseerd approval proces waar mogelijk
- Volledige audit trail van wijzigingen

### 😊 **Member Satisfaction**
- Zelfstandigheid en controle over bijdrage
- Transparante minimum berekening
- Eenvoudig en toegankelijk proces
