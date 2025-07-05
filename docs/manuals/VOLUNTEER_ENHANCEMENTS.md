# Vrijwilligersaccount Verbeteringen

## Nieuwe Functionaliteit

### Automatische User Account Aanmaak
Wanneer een vrijwilligersaccount wordt aangemaakt vanaf de member page, wordt er nu automatisch ook een user account aangemaakt in het systeem.

#### Wat gebeurt er:

1. **Vrijwilliger Creatie**: Wanneer "Create Volunteer Profile" wordt geklikt op een Member page
2. **Email Generatie**: Er wordt automatisch een organisatie email gegenereerd:
   - Format: `voornaam.achternaam@domain.com`
   - Nederlandse tussenvoegsels (van, de, der, etc.) worden automatisch weggelaten
   - Speciale karakters worden opgeschoond
3. **User Account**: Er wordt een System User aangemaakt met:
   - Organisatie email als login
   - Standaard rollen: "Verenigingen Volunteer", "Verenigingen Member"
   - Welcome email wordt verzonden
4. **Koppelingen**: Zowel Member als Volunteer worden gekoppeld aan het nieuwe User account

#### Voorbeeld:
- Member: "Jan van der Berg"
- Gegenereerde email: `jan.berg@veganisme.org`
- User account met access tot het systeem

### Uitgebreide Connections
De Member page toont nu alle gerelateerde documenten in de "Connections" sectie:

#### Memberships Groep:
- **Membership**: Membership records
- **Membership Amendment Request**: Wijzigingsverzoeken
- **Membership Termination Request**: Opzegverzoeken

#### Financial Groep:
- **Sales Invoice**: Facturen
- **SEPA Mandate**: SEPA machtigingen
- **SEPA Direct Debit Batch Entry**: Incasso batch entries

#### Volunteer Groep:
- **Volunteer**: Vrijwilliger profiel
- **Volunteer Activity**: Vrijwilligersactiviteiten
- **Volunteer Assignment**: Toewijzingen
- **Volunteer Expense**: Onkostendeclaraties

#### Administration Groep:
- **User**: Gekoppelde user accounts
- **Customer**: ERPNext customer record

## Technische Details

### Code Wijzigingen

#### 1. volunteer.py - Enhanced create_from_member functie
```python
def create_volunteer_from_member(member_doc):
    # ... bestaande code ...

    # Automatische user account creatie
    user_created = create_organization_user_for_volunteer(volunteer, member_doc)
```

#### 2. Nieuwe create_organization_user_for_volunteer functie
- Genereert schone organisatie email
- Controleert op bestaande users
- Maakt System User aan met juiste rollen
- Koppelt user aan zowel member als volunteer

#### 3. member.json - Uitgebreide links sectie
Toegevoegd links naar alle gerelateerde doctypes voor betere navigation.

### Installatie

Na een `bench migrate` zijn alle wijzigingen actief.

### Gebruik

1. Ga naar een Member document
2. Klik op "Create Volunteer Profile" onder Actions
3. Systeem maakt automatisch:
   - Volunteer record
   - Organisatie user account
   - Email met login gegevens wordt verzonden
4. Bekijk alle gerelateerde documenten in de Connections sectie

### Error Handling

- Als email generatie faalt, wordt alleen volunteer aangemaakt
- Als user account al bestaat, wordt bestaande account gekoppeld
- Foutmeldingen worden gelogd en getoond aan gebruiker
- Cleanup functionaliteit voor failed operations

### Beveiliging

- Alleen geautoriseerde gebruikers kunnen volunteer accounts aanmaken
- User accounts krijgen minimale benodigde rollen
- Audit trail van alle acties
- Proper permission checks op alle operaties
