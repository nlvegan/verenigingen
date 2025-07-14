# Party Deduplication and Matching Implementation Plan

## Current Issues
- Creates duplicate parties with slight variations
- Falls back to generic parties too easily
- No intelligent matching

## Implementation Strategy

### Step 1: Create Party Mapping Infrastructure

1. **E-Boekhouden Relation Mapping DocType**
   ```
   Fields:
   - relation_code (from e-boekhouden)
   - relation_name (from e-boekhouden)
   - party_type (Customer/Supplier)
   - erpnext_party (Link to Customer/Supplier)
   - auto_created (checkbox)
   - last_sync_date
   ```

2. **Matching Score Algorithm**
   ```python
   def calculate_match_score(ebh_name, erp_name):
       score = 0

       # Exact match
       if ebh_name.lower() == erp_name.lower():
           return 100

       # Fuzzy matching
       from difflib import SequenceMatcher
       ratio = SequenceMatcher(None, ebh_name.lower(), erp_name.lower()).ratio()
       score += ratio * 50

       # Check for common variations
       if remove_company_suffixes(ebh_name) == remove_company_suffixes(erp_name):
           score += 30

       # Check VAT number match if available
       if vat_numbers_match(ebh_name, erp_name):
           score += 20

       return min(score, 99)  # Never auto-match at 100%
   ```

### Step 2: Implement Smart Party Resolution

1. **Party Resolution Flow**
   ```python
   def get_or_create_party(relation_data, party_type):
       # 1. Check existing mapping
       mapping = frappe.db.get_value('E-Boekhouden Relation Mapping', {
           'relation_code': relation_data.get('code')
       })

       if mapping:
           return mapping.erpnext_party

       # 2. Search for matches
       matches = find_potential_matches(relation_data, party_type)

       # 3. Auto-match if confidence > 85%
       if matches and matches[0]['score'] > 85:
           create_mapping(relation_data, matches[0]['party'])
           return matches[0]['party']

       # 4. Queue for manual review if matches exist
       if matches:
           create_review_task(relation_data, matches, party_type)
           return None  # Don't create party yet

       # 5. Create new party
       return create_party_from_relation(relation_data, party_type)
   ```

2. **Manual Review Interface**
   - Page showing unmatched relations
   - Side-by-side comparison
   - Ability to create new or link existing
   - Bulk operations support

### Step 3: Enhance Party Creation

1. **Extract More Data from E-Boekhouden**
   ```python
   def create_party_from_relation(relation_data, party_type):
       party = frappe.new_doc(party_type)

       # Smart name extraction
       party.customer_name = clean_party_name(relation_data.get('name'))
       party.eboekhouden_relation_code = relation_data.get('code')

       # Extract VAT number from name or description
       vat_number = extract_vat_number(relation_data)
       if vat_number:
           party.tax_id = vat_number

       # Extract address if available
       if relation_data.get('address'):
           create_address_for_party(party, relation_data['address'])

       # Set customer group/supplier group intelligently
       party.customer_group = detect_customer_group(relation_data)

       party.insert()

       # Create mapping
       create_mapping(relation_data, party.name)

       return party.name
   ```

### Step 4: Cleanup Existing Data

1. **Deduplication Script**
   ```python
   def cleanup_duplicate_parties():
       # Find potential duplicates
       duplicates = find_duplicate_parties()

       for dup_group in duplicates:
           # Merge transactions to primary party
           primary = dup_group[0]
           for duplicate in dup_group[1:]:
               merge_party_transactions(duplicate, primary)

           # Update mappings
           update_relation_mappings(dup_group, primary)
   ```

2. **Validation Rules**
   - Prevent creation of parties with generic names
   - Require minimum information for new parties
   - Flag suspicious patterns
