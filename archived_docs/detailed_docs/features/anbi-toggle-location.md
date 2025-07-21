# ANBI Toggle Location

## Finding the ANBI Enable/Disable Toggle

To enable or disable ANBI functionality in the Verenigingen app:

1. **Navigate to Verenigingen Settings**:
   - Go to the main menu
   - Search for "Verenigingen Settings" or navigate to it from the Verenigingen module

2. **Locate the ANBI Section**:
   - Scroll down to the **"ANBI (Tax-Deductible Donations) Settings"** section
   - This section is located after the "Donation Settings" section

3. **Find the Toggle**:
   - The first field in this section is **"Enable ANBI Functionality"** (checkbox)
   - When checked (default): All ANBI features are enabled
   - When unchecked: All ANBI features are disabled

4. **Related ANBI Settings** (visible when enabled):
   - **Organization has ANBI Status**: Whether your organization has official ANBI status
   - **ANBI Minimum Reportable Amount**: Threshold for automatic Belastingdienst reporting
   - **Default Donor Type**: Default type for new donors (Individual/Organization)

## What the Toggle Controls

When ANBI functionality is **ENABLED**:
- Periodic Donation Agreements can qualify for ANBI tax benefits (5+ years)
- BSN/RSIN fields are available on Donor records
- ANBI consent tracking is active
- Tax receipt generation features are available
- Belastingdienst reporting features are active

When ANBI functionality is **DISABLED**:
- The system functions as a regular donation management system
- No special Dutch tax compliance features
- Periodic agreements are treated as regular pledges
- No BSN/RSIN collection or encryption
- No ANBI-specific reporting

## Technical Details

The toggle is stored as `enable_anbi_functionality` in Verenigingen Settings and controls:
- Field visibility via `depends_on` conditions
- Validation logic in Periodic Donation Agreements
- ANBI eligibility calculations
- Tax benefit applicability
