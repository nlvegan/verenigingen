# E-Boekhouden REST API Limitations

## Summary
The E-Boekhouden REST API has critical limitations that make it unsuitable for complete data migration:

## Issues Found

### 1. Mutation List Endpoint Returns Incomplete Data
- The `/v1/mutation` endpoint returns mutations with `id=0` for all records
- Other fields are incomplete (no description, no mutation lines)
- This makes it impossible to identify which mutations to fetch details for

### 2. No Reliable Way to Iterate Through All Mutations
- Without real IDs in the list response, we can't systematically fetch all mutation details
- We would need to guess/probe mutation IDs, which is unreliable and inefficient

### 3. Authentication Works But Data Access is Limited
- Session token authentication works correctly
- The API accepts the token and returns data
- But the data structure makes it unusable for migration purposes

## Example Response from `/v1/mutation`
```json
{
  "items": [
    {
      "id": 0,  // All mutations have id=0
      "type": 0,
      "date": "2018-12-31",
      "invoiceNumber": "",
      "ledgerId": 13201861,
      "amount": 400.0,
      "entryNumber": ""
    }
    // ... more items with id=0
  ],
  "count": 5
}
```

## Detail Endpoint Works But Requires Known IDs
- `/v1/mutation/{id}` returns complete data when given a valid ID
- But without the IDs from the list endpoint, we can't use this effectively

## Conclusion
Due to these limitations, the migration continues to use the SOAP API despite its 500-record limitation. The REST API would need to be fixed by E-Boekhouden to return actual mutation IDs in the list response.

## Workaround Attempts
1. Tried fetching details for each item - failed due to id=0
2. Tried guessing mutation IDs - unreliable and would miss records
3. Tried using other fields as identifiers - insufficient data in list response

## Recommendation
Continue using SOAP API until E-Boekhouden fixes their REST API to return proper mutation IDs in the list endpoint.
