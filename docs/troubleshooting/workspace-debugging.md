# Workspace Debugging Guide

This guide documents the debugging process for Frappe workspace display issues, specifically when workspaces show "0 links" or fail to render properly.

## Common Workspace Issues

### Issue 1: Workspace Shows 0 Links
**Symptoms:**
- Workspace appears empty or shows 0 links in UI
- Debug API shows correct link count but UI doesn't display them
- Users cannot access workspace functionality

**Root Causes:**
- Broken DocType links pointing to non-existent doctypes
- Corrupted workspace cache
- Invalid workspace content structure
- Duplicate or malformed links

### Issue 2: Migration Errors in Scheduled Tasks
**Symptoms:**
- Error messages during app installation: `No module named 'module_name'`
- Scheduler failures referencing old/renamed modules
- Migration warnings about invalid method paths

## Frappe Built-in Debugging Tools

Frappe provides several built-in commands for workspace debugging. **Always try these first** before custom solutions:

### 1. Clear Cache (Most Common Fix)
```bash
bench --site <site_name> clear-cache
```
**When to use:** First line of defense for any UI display issues, workspace rendering problems, or after making configuration changes.

### 2. Reload DocType
```bash
bench --site <site_name> reload-doctype Workspace
```
**When to use:** When workspace structure appears corrupted or after workspace configuration changes.

### 3. Reinstall App (Nuclear Option)
```bash
bench --site <site_name> install-app <app_name> --force
```
**When to use:** When workspace is completely broken and cache clearing doesn't help. This restores all fixtures including workspace configuration.

## Diagnostic Commands

### Check Workspace Status
Use the custom debug API to get detailed workspace information:
```bash
bench --site <site_name> execute "verenigingen.api.workspace_debug.check_workspace_status"
```

**Expected Output:**
```json
{
  "success": true,
  "data": {
    "name": "Verenigingen",
    "links_count": 119,
    "public": 1,
    "hidden": 0,
    "workflow_demo_found": true,
    "page_links": [...],
    "broken_links": []
  }
}
```

### Identify Broken Links
Check for DocType links pointing to non-existent doctypes:
```sql
SELECT link_type, link_to, COUNT(*) as count
FROM `tabWorkspace Link`
WHERE parent = 'Verenigingen' AND link_type = 'DocType'
GROUP BY link_to
ORDER BY link_to;
```

Cross-reference with existing doctypes:
```sql
SELECT name FROM tabDocType WHERE name = '<link_to_value>';
```

## Step-by-Step Debugging Process

### Step 1: Basic Diagnostics
1. **Check workspace status** using debug API
2. **Identify broken links** using SQL queries
3. **Note link counts** and compare with expected values

### Step 2: Apply Frappe Built-in Fixes
1. **Clear cache** first:
   ```bash
   bench --site <site_name> clear-cache
   ```

2. **Reload workspace doctype**:
   ```bash
   bench --site <site_name> reload-doctype Workspace
   ```

3. **Test workspace** - check if issue is resolved

### Step 3: Manual Cleanup (If Needed)
If built-in tools don't resolve the issue:

1. **Remove broken DocType links**:
   ```sql
   DELETE FROM `tabWorkspace Link`
   WHERE parent = 'Verenigingen' AND link_to = '<non_existent_doctype>';
   ```

2. **Remove duplicate links**:
   ```sql
   DELETE FROM `tabWorkspace Link`
   WHERE parent = 'Verenigingen' AND label = '<duplicate_label>'
   AND idx > (SELECT MIN(idx) FROM (SELECT idx FROM `tabWorkspace Link`
   WHERE parent = 'Verenigingen' AND label = '<duplicate_label>') AS temp);
   ```

3. **Update workspace timestamp** to force refresh:
   ```sql
   UPDATE tabWorkspace SET modified = NOW() WHERE name = 'Verenigingen';
   ```

### Step 4: Nuclear Option
If all else fails, reinstall the app:
```bash
bench --site <site_name> install-app verenigingen --force
```

## Fixing Migration Errors

### Scheduler Hook Errors
**Problem:** Old module paths in `hooks.py` causing scheduler failures.

**Example Error:**
```
verenigingen.verenigingen.doctype.membership_amendment_request.membership_amendment_request.process_pending_amendments is not a valid method: No module named 'verenigingen.verenigingen.doctype.membership_amendment_request'
```

**Solution:** Update `hooks.py` with correct module paths:
```python
# OLD (broken)
"verenigingen.verenigingen.doctype.membership_amendment_request.membership_amendment_request.process_pending_amendments"

# NEW (correct)
"verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.process_pending_amendments"
```

**Verification:** Test the scheduler function:
```bash
bench --site <site_name> execute "verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.process_pending_amendments"
```

### Pre-commit Hook Import Errors (NEW - January 2025)
**Problem:** Pre-commit hooks failing with `ModuleNotFoundError: No module named 'barista'` or similar import errors.

**Root Cause:** Pre-commit hooks attempting to run bench commands outside of Frappe environment context.

**Example Error:**
```bash
Run quick validation tests......................Failed
- hook id: run-quick-tests
- exit code: 1
ModuleNotFoundError: No module named 'barista'
```

**Solution:** Update `.pre-commit-config.yaml` to use direct Python script execution:
```yaml
# ❌ OLD (fails with module imports)
- id: run-quick-tests
  name: Run quick validation tests
  entry: bench --site dev.veganisme.net execute "module.function"

# ✅ NEW (works reliably)
- id: run-quick-tests
  name: Run quick validation tests
  entry: python scripts/testing/integration/simple_test.py
  language: system
```

**Key Changes Made:**
- Changed from bench command execution to direct Python script execution
- Updated test entry points to use standalone scripts
- Enhanced validation scripts to work independently of Frappe context

**Verification:** Test the updated hook:
```bash
# Run the updated pre-commit hook manually
python scripts/testing/integration/simple_test.py

# Run all pre-commit hooks
pre-commit run --all-files
```

**Benefits:**
- More reliable pre-commit execution
- Faster hook execution (no bench overhead)
- Better error reporting and debugging
- Independence from Frappe environment setup

## Prevention Best Practices

### 1. Workspace Management
- **Never manually edit workspace links** in production
- **Use fixtures** for workspace configuration
- **Test workspace changes** in development first
- **Document any custom workspace modifications**

### 2. Pre-commit Workspace Validation
The project includes automatic workspace validation in pre-commit hooks:

**Configuration:** `.pre-commit-config.yaml` includes `workspace-validator` hook
**Validation Script:** `scripts/validation/workspace_pre_commit.py`
**API Endpoint:** `verenigingen.api.workspace_validator.run_workspace_pre_commit_check`

**What it validates:**
- Workspace exists and is properly configured
- No broken DocType links (prevents rendering failures)
- No broken Report links
- Essential page links are present
- Card break structure is valid
- Content JSON structure is valid

**When it runs:** Automatically triggered when workspace-related files are modified:
- `verenigingen/fixtures/workspace.json`
- `verenigingen/api/workspace_*.py`

**Manual execution:**
```bash
# Run validation directly
python scripts/validation/workspace_pre_commit.py

# Run via API
bench --site <site> execute "verenigingen.api.workspace_validator.run_workspace_pre_commit_check"
```

### 2. Module Refactoring
- **Update all references** when renaming doctypes/modules
- **Check hooks.py** for scheduler references
- **Update import statements** throughout codebase
- **Test migration process** thoroughly

### 3. Regular Maintenance
- **Monitor workspace health** with debug APIs
- **Clear cache regularly** after updates
- **Validate workspace fixtures** match database state
- **Keep documentation updated** with workspace changes

## Related Files

### Workspace Configuration
- **Fixtures:** `/verenigingen/fixtures/workspace.json`
- **Debug API:** `/verenigingen/api/workspace_debug.py`
- **Hooks:** `/verenigingen/hooks.py`

### Migration Patches
- **Workspace Restoration:** `/verenigingen/patches/v2_0/add_workflow_demo_to_workspace.py`
- **Patches Registry:** `/verenigingen/patches.txt`

## Troubleshooting Checklist

When encountering workspace issues:

- [ ] Clear cache (`bench clear-cache`)
- [ ] Reload Workspace doctype
- [ ] Check for broken DocType links
- [ ] Verify workspace link counts
- [ ] Remove duplicate/invalid links
- [ ] Check hooks.py for invalid module references
- [ ] Test scheduler functions
- [ ] Consider app reinstall if severe corruption
- [ ] Update workspace modified timestamp
- [ ] Document any manual fixes applied

## Success Metrics

A healthy workspace should show:
- **Links Count:** >100 links for Verenigingen workspace
- **Broken Links:** 0 broken links
- **Workflow Demo:** Found and accessible
- **Page Links:** All portal pages accessible
- **Public Status:** Public = 1, Hidden = 0

## Contact Information

For complex workspace issues or if this guide doesn't resolve the problem:
1. Check Frappe Framework documentation for workspace management
2. Review recent changes to workspace fixtures
3. Consult with system administrators
4. Consider opening issue in project repository

---

**Last Updated:** 2025-01-20
**Tested On:** Frappe v15, ERPNext v15
**App Version:** Verenigingen v2.0+
