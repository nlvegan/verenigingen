# Bandit Security Configuration Guide

## Overview
This document explains how to configure Bandit to focus on production code security issues by excluding archives, tests, and development files.

## Current Results

### Before Exclusions
- **Total issues**: 1,121
- **High confidence**: 972
- **High severity**: 7

### After Exclusions
- **Total issues**: 575 (48.7% reduction)
- **High confidence**: 464 (52.2% reduction)
- **High severity**: 7 (same - all in production code)

## Configuration Files

### .bandit Configuration
The `.bandit` file in the project root configures exclusions:

```ini
# Bandit security configuration for Verenigingen
[bandit]
exclude_dirs = archived_docs,archived_removal,archived_unused,phase4_removed_files_backup,one-off-test-utils,node_modules,.pytest_cache
skips = B101,B601
severity = HIGH
```

### Pre-commit Hook Configuration
Update your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/PyCQA/bandit
  rev: '1.7.5'
  hooks:
    - id: bandit
      args: ['--configfile', '.bandit', '--exclude', 'archived_*,*_backup*,test_*,*_test.py']
```

## Excluded Directories

### Archives & Backups
- `archived_docs/` - Old documentation
- `archived_removal/` - Removed code archives
- `archived_unused/` - Unused code backup (546 issues)
- `phase4_removed_files_backup/` - Development cleanup backup
- `one-off-test-utils/` - Temporary debugging scripts

### Development Files
- `node_modules/` - JavaScript dependencies
- `.pytest_cache/` - Test cache files

## Remaining Critical Issues (Production Code Only)

### HIGH Severity Issues (7 total)

1. **Command Injection (B602) - 5 instances**
   - Scripts: `generate_version.py`, validation test runners
   - Risk: `shell=True` in subprocess calls
   - **Action Required**: Switch to `shell=False` or validate inputs

2. **Weak Hash Algorithm (B324) - 2 instances**
   - Files: Address matching modules
   - Risk: MD5 used (but not for security)
   - **Action Required**: Add `usedforsecurity=False`

### MEDIUM Severity Issues (11 total)
- XML parsing without defusedxml (9 instances)
- Eval usage (1 instance)
- Other XML issues (1 instance)

## Recommended Actions

### Immediate (HIGH Priority)
```python
# Fix subprocess calls
subprocess.run(["git", "log"], shell=False)  # Instead of shell=True

# Fix MD5 usage
hashlib.md5(data, usedforsecurity=False).hexdigest()
```

### Medium Priority
```python
# Replace XML parsing
import defusedxml.ElementTree as ET
ET.fromstring(xml_data)  # Instead of xml.etree.ElementTree
```

## Benefits of This Configuration

1. **Focused Reports**: Only shows issues in production code
2. **Reduced Noise**: 48.7% fewer false positives from archives
3. **Actionable Results**: Clear list of 7 actual security issues
4. **CI/CD Efficiency**: Faster scans, relevant results

## Command Line Usage

```bash
# Use the config file
bandit -r . -c .bandit

# Or with explicit exclusions
bandit -r . --exclude archived_docs,archived_removal,archived_unused,phase4_removed_files_backup,one-off-test-utils

# Focus on high severity only
bandit -r . --severity-level high
```

## Validation

After implementing exclusions, you should see:
- ~575 total issues (down from 1,121)
- 7 HIGH severity issues requiring attention
- All issues in actual production code paths

This makes the security scan actionable and focused on real vulnerabilities.
