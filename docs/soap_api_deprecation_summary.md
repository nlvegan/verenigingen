# SOAP API Deprecation Summary

## Date: 2025-01-08

### Changes Made:

1. **Added Deprecation Warnings** to SOAP API files:
   - `eboekhouden_soap_api.py`: Added comprehensive deprecation warning at the top
   - `eboekhouden_soap_migration.py`: Added deprecation warning directing to REST API

2. **Updated Transaction Import to Use REST API**:
   - Modified `start_transaction_import()` in `e_boekhouden_migration.py`
   - "Recent Transactions" now imports last 90 days via REST API (instead of 500 via SOAP)
   - "All Transactions" continues to use REST API for complete history
   - Both options now require REST API token configuration

3. **Updated `migrate_transactions_data()` Method**:
   - Removed SOAP API usage as default
   - Now always uses REST API for transaction migration
   - SOAP-related flags are ignored

4. **Updated UI to Reflect Changes**:
   - Changed "Recent 500 (SOAP API)" to "Recent Transactions (Last 90 days)"
   - Changed "All Transactions (REST API)" to "All Transactions (Complete history)"
   - Updated migration guide to show both options use REST API
   - Removed 500 transaction limit warnings
   - Added positive messaging about REST API usage

### Benefits:

1. **No More 500 Transaction Limit**: Recent transactions can now import more than 500 records
2. **Consistent API Usage**: Everything uses REST API, reducing complexity
3. **Better Performance**: REST API is faster and more reliable
4. **Future Proof**: SOAP API can be fully removed in future versions

### Migration Impact:

- Existing migrations will continue to work
- New migrations will automatically use REST API
- Users must configure REST API token in E-Boekhouden Settings
- The "Recent Transactions" option now provides last 90 days instead of last 500 records

### Next Steps:

1. **Monitor**: Watch for any issues with the new REST-only approach
2. **Documentation**: Update user documentation to reflect REST API requirement
3. **Future Cleanup**: Consider removing SOAP code entirely in next major version

### Important Notes:

- Bench restart NOT performed yet (as requested)
- To apply these changes, run: `bench restart`
- SOAP API code remains for backward compatibility but is not used for new operations
