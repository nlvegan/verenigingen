# Simplified Monitoring Structure (Development)

## Current Structure

```
verenigingen/
├── monitoring/
│   └── zabbix_integration.py  # Simple import from scripts/monitoring/
└── scripts/
    └── monitoring/
        ├── zabbix_integration.py  # All implementation code
        ├── Templates/
        │   └── *.yaml  # Zabbix templates
        └── Docs/
            └── *.md    # Documentation
```

## Why This Structure?

1. **Clear Separation**: Implementation in scripts/, API exposure in app module
2. **Single Source**: All code in one file (zabbix_integration.py)
3. **No Duplication**: No backward compatibility needed during development
4. **Easy Testing**: Can modify implementation without changing imports

## Recommendations for Further Simplification

Since we're in development, consider:

1. **Rename for Clarity**: ✓ DONE
   - Already renamed to `zabbix_integration.py`

2. **Consolidate Templates**: Keep only the recommended template
   - Keep: `zabbix_template_frappe_v7.2_fixed.yaml`
   - Remove: Older/compatibility versions

3. **Merge Documentation**: Combine all docs into one README.md

4. **Remove Version Checks**: Assume Zabbix 7.0+ everywhere

## Benefits of Simplified Structure

- **Less Confusion**: One implementation file, one import
- **Easier Maintenance**: All code in one place
- **Modern Stack**: Zabbix 7.0+ features by default
- **Clean Codebase**: No legacy cruft

## Next Development Steps

1. Run cleanup script to remove old files
2. Test all endpoints work
3. Consider further simplifications
4. Document any app-specific metrics