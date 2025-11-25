# Workspace Validators

**Status**: ⚙️ Workspace Management
**Count**: 2 validators

These validators ensure workspace configuration integrity and detect content synchronization issues.

## Validators in This Directory

- **workspace_validator.py** - Comprehensive workspace validation requiring Frappe environment
- **workspace_integrity_validator.py** - Pre-commit wrapper for workspace configuration integrity

## Usage

### Workspace Validation
```bash
# Validate workspace content synchronization
bench --site dev.veganisme.net execute "verenigingen.utils.workspace_content_fixer.fix_workspace_content" --args "['Verenigingen', false]"

# Analyze workspace structure
bench --site dev.veganisme.net execute "verenigingen.utils.workspace_analyzer.print_analysis" --args "['Verenigingen']"
```

### Pre-commit Integration
```bash
# Quick workspace integrity check
python scripts/validation/workspace/workspace_integrity_validator.py
```

## Common Issues

Workspace validators detect:
- ✅ Empty sections (headers without cards)
- ✅ Content field vs Card Break synchronization mismatches
- ✅ Section hierarchy issues (improper header→card→spacer patterns)
- ✅ Missing Card Break entries
- ✅ Configuration integrity problems

## Integration

The workspace validators work with:
- `verenigingen/utils/workspace_analyzer.py` - Content vs database structure analysis
- `verenigingen/utils/workspace_link_validator.py` - Link validation
- `verenigingen/utils/workspace_content_fixer.py` - Content field repairs
- `scripts/workspace_debugging_toolkit.py` - Comprehensive debugging tools

## Documentation

See:
- `docs/troubleshooting/workspace-debugging.md` - Detailed workspace troubleshooting guide
- `docs/validation_tool_inventory.md` - Complete validator capabilities
