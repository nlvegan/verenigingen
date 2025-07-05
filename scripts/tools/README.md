# Developer Tools

Developer utilities and helper scripts.

## Available Tools

- **`claude_regression_helper.py`** - Regression testing helper for Claude Code development
- **`console_commands.py`** - Useful console commands and utilities

## Usage

```bash
# Use Claude regression helper
python scripts/tools/claude_regression_helper.py pre-change
python scripts/tools/claude_regression_helper.py post-change

# Access console commands
python scripts/tools/console_commands.py
```

## Tool Categories

- **Testing Helpers** - Tools to assist with testing and validation
- **Development Utilities** - General development support tools
- **Console Tools** - Interactive utilities for development

## Claude Regression Helper

The Claude regression helper provides:

- Pre-change baseline testing
- Post-change regression testing
- Targeted component testing
- Coverage reporting
- Performance metrics

### Usage Examples

```bash
# Run baseline tests before making changes
python scripts/tools/claude_regression_helper.py pre-change

# Test specific component during development
python scripts/tools/claude_regression_helper.py targeted volunteer

# Run full regression after changes
python scripts/tools/claude_regression_helper.py post-change

# Generate coverage report
python scripts/tools/claude_regression_helper.py coverage
```

## Adding Developer Tools

When adding new tools:

1. Focus on developer productivity
2. Include comprehensive help/usage information
3. Make tools scriptable and automatable
4. Document integration with existing workflows
5. Consider cross-platform compatibility
