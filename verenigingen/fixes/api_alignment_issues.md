# E-Boekhouden REST API Alignment Issues

After reviewing the actual REST API specification, several assumptions in the implementation plans need correction:

## 1. VAT/BTW Handling - NEEDS REVISION
**Current Plan Assumptions:**
- ❌ Assumed fields: `vatAmount`, `vatPercentage`, `vatCode`, `vatInclusive`

**Actual API:**
- ✅ VAT is handled through `BtwCode` (VAT code) field
- ✅ Predefined VAT codes like `HOOG_VERK_21`, `LAAG_VERK_9`, `GEEN`
- ✅ VAT amount calculated from line items, not stored separately
- ✅ Each line item can have its own VAT code

**Required Changes:**
- Map Dutch VAT codes to ERPNext tax templates
- Calculate VAT from line items rather than expecting a total
- Support VAT code per line item

## 2. Multi-line Items - PARTIALLY CORRECT
**Current Plan Assumptions:**
- ✅ Correctly assumed line items array exists

**Actual API:**
- ✅ `Regels` array contains line items
- ✅ Each line has: `Aantal` (quantity), `Eenheid` (unit), `Code` (product code)
- ✅ `Prijs` (price), `Omschrijving` (description), `BTWCode`
- ✅ `GrootboekNummer` (ledger account)

**Required Changes:**
- Use `Regels` instead of generic `lines`
- Map `GrootboekNummer` to ERPNext accounts per line
- Handle `Eenheid` (unit) field properly

## 3. Invoice Metadata - NEEDS MAJOR REVISION
**Current Plan Assumptions:**
- ❌ Assumed fields: `dueDate`, `paymentDays`, `contactPerson`, `paymentStatus`

**Actual API:**
- ✅ `FactuurDatum` (invoice date)
- ✅ `Betalingstermijn` (payment term in days)
- ❌ No explicit due date field (must calculate)
- ❌ No contact person field on invoices
- ❌ No payment status field

**Required Changes:**
- Calculate due date from `FactuurDatum` + `Betalingstermijn`
- Remove contact person extraction from invoices
- Remove payment status tracking (not available)

## 4. Party/Relation Data - LIMITED
**Current Plan Assumptions:**
- ❌ Assumed rich relation data with addresses, VAT numbers

**Actual API:**
- ✅ Relations have `Code` and `Omschrijving` (description)
- ✅ Basic fields like email, phone
- ❌ No VAT number in relation data
- ❌ Limited address information

**Required Changes:**
- Simplify party matching to use Code and Description only
- Remove VAT-based matching
- Don't expect detailed address data

## 5. Transaction Types - DIFFERENT STRUCTURE
**Current Plan Assumptions:**
- ✅ Correctly identified numeric mutation types

**Actual API Mutation Types:**
- `GeldOntvangen` (Money received)
- `GeldUitgegeven` (Money spent)
- `FactuurOntvangen` (Invoice received)
- `FactuurVerstuurd` (Invoice sent)
- `FactuurbetalingOntvangen` (Invoice payment received)
- `FactuurbetalingVerstuurd` (Invoice payment sent)
- `MemoriaalboekingDoorvoeren` (Journal entry)

## 6. Additional API Capabilities Not Considered

**Useful Features Available:**
- `Inkoopboeking` endpoint for purchase entries
- `Verkoopboeking` endpoint for sales entries
- Separate endpoints for creating vs fetching data
- `Kostplaats` (cost center) support
- `Dagboeken` (journal) categorization

**Limitations to Consider:**
- 2000 record limit per request
- Session-based authentication (timeout considerations)
- Some modules require specific subscriptions

## Recommended Plan Adjustments

### High Priority:
1. Revise VAT handling to use BtwCode mapping
2. Adjust metadata extraction to available fields
3. Simplify party matching logic
4. Use proper Dutch field names from API

### Medium Priority:
1. Implement cost center mapping
2. Add journal (dagboek) categorization
3. Handle 2000 record pagination properly

### Low Priority:
1. Leverage specialized endpoints (Inkoopboeking, Verkoopboeking)
2. Add subscription tier detection
3. Implement session management for long imports
