# Test Utilities

This directory contains development utilities and debugging tools for the controller testing infrastructure.

## Files

### `debug_controller_loading.js`

**Purpose**: Standalone debugging tool for verifying controller loading infrastructure works correctly.

**Usage**:
```bash
node verenigingen/tests/utils/debug_controller_loading.js
```

**When to use**:
- Controller loading fails mysteriously in Jest tests
- Need to quickly test a specific controller without full test setup  
- Debugging VM sandboxing or handler extraction issues
- Verifying controller loading works after infrastructure changes

**Output**: Loads the Volunteer controller and tests basic events (refresh, member) with console output showing success/failure.

**Note**: This is a development utility only. For formal testing, use the Jest test suites in `tests/unit/doctype/`.

## Adding New Utilities

When adding new debugging or development utilities:

1. **File naming**: Use descriptive names with `debug_` prefix
2. **Documentation**: Include comprehensive JSDoc headers explaining purpose
3. **Scope**: Keep utilities focused on single debugging tasks
4. **Dependencies**: Minimize external dependencies where possible
5. **Error handling**: Include proper error handling and informative messages

## Related Infrastructure

- `../setup/controller-loader.js` - Core controller loading with VM sandboxing
- `../setup/controller-test-base.js` - Centralized test infrastructure  
- `../setup/domain-test-builders.js` - Domain-specific test builders
- `../unit/doctype/` - Formal Jest test suites