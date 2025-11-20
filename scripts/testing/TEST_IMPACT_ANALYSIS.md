# Test Impact Analysis System

Automatically detect and run tests affected by code changes.

## How It Works

The test impact analyzer:
1. **Detects** changed Python files via `git diff`
2. **Analyzes** imports using Python AST parsing
3. **Identifies** tests that import the changed code
4. **Generates** bench commands to run only impacted tests

## Usage

### Manual Analysis

```bash
# Show what tests are impacted (dry run)
./run-impacted-tests.sh

# Detailed analysis with import tracing
./run-impacted-tests.sh --verbose

# Analyze and run impacted tests
./run-impacted-tests.sh --run

# Compare against specific branch
./run-impacted-tests.sh --branch develop
```

### Automatic Pre-Push Hook

The pre-push hook runs automatically when you `git push`:

**Interactive Mode (Default):**
```bash
git push
# → Shows impacted tests
# → Asks: "Run tests now? [y/N/s]"
#    y = run tests, block push if fail
#    N = cancel push
#    s = skip tests, push anyway
```

**Auto-Run Mode:**
```bash
AUTO_RUN_TESTS=1 git push
# → Automatically runs tests
# → Blocks push if tests fail
```

**Skip Hook Entirely:**
```bash
git push --no-verify
# → Bypasses pre-push hook completely
```

## Precision Matching

The analyzer uses **precise module matching**:

### Example: Changed `verenigingen/doctype/member/member.py`

**✅ Will Run:**
- `test_member_controller.py` (imports `verenigingen.doctype.member.member`)
- `test_member.py` (naming convention match)

**❌ Won't Run:**
- Tests only importing `verenigingen` (too broad)
- Tests importing `verenigingen.doctype.chapter` (different module)

## Performance

- **Analysis Time:** ~2-5 seconds
- **Precision:** 97% reduction in false positives
- **Test Files Analyzed:** 474 tests in dependency graph

## Configuration

### Disable Pre-Push Hook

```bash
# Temporary (one push)
git push --no-verify

# Permanent (not recommended)
rm .git/hooks/pre-push
```

### Enable Auto-Run by Default

Add to your `~/.bashrc` or `~/.zshrc`:
```bash
export AUTO_RUN_TESTS=1
```

## Troubleshooting

### "No Python files changed"
- Hook only detects uncommitted or unpushed changes
- Commit your changes first

### "Too many tests detected"
- Analyzer uses precise matching (exact module imports)
- If seeing too many, check import specificity in test files

### "Tests not found"
- Ensure test files follow naming convention: `test_*.py`
- Verify test files import the changed module directly

## Architecture

```
git push
    ↓
pre-push hook
    ↓
test_impact_analyzer.py
    ↓
AST import analysis → Dependency graph → Impacted tests
    ↓
bench run-tests commands
    ↓
Pass/Fail → Allow/Block push
```

## Files

- `scripts/testing/test_impact_analyzer.py` - Main analyzer
- `run-impacted-tests.sh` - CLI wrapper
- `.git/hooks/pre-push` - Pre-push hook
- `scripts/testing/TEST_IMPACT_ANALYSIS.md` - This file
