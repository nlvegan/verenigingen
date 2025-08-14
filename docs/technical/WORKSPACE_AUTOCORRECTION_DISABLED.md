# Workspace Auto-Correction Safety Measures

**Date**: 2025-08-14
**Reason**: Prevent workspace corruption from broken link clicks

## Disabled Auto-Correction Functions

The following workspace auto-correction functions have been disabled with safety guards to prevent accidental workspace corruption:

### 1. `workspace_content_fixer.py`
- **Function**: `fix_workspace_content()`
- **Risk**: Automatically removes "orphaned cards" from workspace content
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/verenigingen/utils/workspace_content_fixer.py`

### 2. `check_and_fix_workspace.py`
- **Function**: `check_and_fix_workspace()`
- **Risk**: Automatically adds Communication section to workspace
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/verenigingen/api/check_and_fix_workspace.py`

### 3. `rebuild_workspace.py` ⚠️ HIGHLY DESTRUCTIVE
- **Function**: `rebuild_workspace()`
- **Risk**: Completely rebuilds workspace from fixtures (destructive)
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/verenigingen/api/rebuild_workspace.py`

### 4. `fix_workspace.py`
- **Function**: `fix_workspace()`
- **Risk**: Automatically adds Newsletter links to workspace
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/verenigingen/api/fix_workspace.py`

### 5. `execute_workspace_reorg.py`
- **Function**: `fix_content_sync()`
- **Risk**: Executes workspace reorganization without user consent
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/verenigingen/utils/execute_workspace_reorg.py`

### 6. `fix_workspace_links.py`
- **Function**: `fix_workspace_links()`
- **Risk**: Automatically removes broken links from workspace
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/verenigingen/api/fix_workspace_links.py`

### 7. `restore_workspace.py` ⚠️ HIGHLY DESTRUCTIVE
- **Function**: `restore_workspace()`
- **Risk**: Overwrites current workspace with fixture data
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/verenigingen/api/restore_workspace.py`

### 8. `fix_eboekhouden_workspace.py`
- **Function**: `install_eboekhouden_workspace()`
- **Risk**: Creates/modifies E-Boekhouden workspace
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/scripts/fix_eboekhouden_workspace.py`

### 9. `add_workflow_demo_to_workspace.py` ⚠️ MIGRATION PATCH
- **Function**: `execute()`
- **Risk**: Reloads workspace from fixtures during migration
- **Disabled**: Patch completely skipped for safety
- **Location**: `/verenigingen/patches/v2_0/add_workflow_demo_to_workspace.py`

### 10. `scripts/api_maintenance/fix_workspace.py`
- **Function**: `install_eboekhouden_workspace()`
- **Risk**: Installs E-Boekhouden workspace
- **Disabled**: Requires `force_enable=True` to run
- **Location**: `/scripts/api_maintenance/fix_workspace.py`

### 11. `workspace_reorganization.py` ⚠️ EXTREMELY DESTRUCTIVE
- **Function**: `reorganize_workspace()`
- **Risk**: DELETES ALL WORKSPACE LINKS then rebuilds from scratch
- **Disabled**: Requires `force_enable=True` to run (NOT RECOMMENDED)
- **Location**: `/scripts/workspace_reorganization.py`

## How to Use Safely

If you need to run any of these functions, use the safety override:

```python
# For API calls
result = check_and_fix_workspace(force_enable=True)

# For direct function calls
result = fix_workspace_content("Verenigingen", dry_run=False, force_enable=True)
```

## Recommended Safe Alternatives

Instead of using auto-correction, use the manual validation tools:

```bash
# Validate workspace health
echo "exec(open('/tmp/validation_script.py').read())" | bench --site [site] console

# Backup before any changes
bench --site [site] export-doc Workspace Verenigingen

# Make changes manually using the step-by-step process in workspace-debugging-guide.md
```

## Re-enabling Auto-Correction

To re-enable auto-correction in the future:

1. Remove the safety guard checks from each function
2. Test thoroughly in development environment first
3. Document any changes to workspace behavior
4. Update this document with new risk assessment

## Monitoring

Monitor these logs for potential auto-correction attempts:

```bash
# Check for disabled auto-correction calls
grep -r "WORKSPACE.*DISABLED FOR SAFETY" /path/to/logs/
```

This safety measure prevents the workspace corruption issue described in the workspace debugging guide while preserving the ability to manually run correction tools when needed.
