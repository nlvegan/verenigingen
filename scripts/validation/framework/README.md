# Framework & Orchestration Validators

**Status**: 🔧 Framework Infrastructure
**Count**: 6 validators

These validators provide orchestration, configuration, and framework capabilities that support the entire validation ecosystem.

## Validators in This Directory

### High-Level Orchestration
- **validation_suite_runner.py** - Central coordinator running multiple validation tools with unified reporting
- **unified_validation_engine.py** - Advanced orchestration with intelligent routing and caching

### Base Framework
- **validation_framework.py** - Base framework providing common validation patterns and utilities
- **validation_config.py** - Configuration management infrastructure with ValidationLevel enum

### Core Analysis
- **ast_field_analyzer.py** - Deep AST analysis engine with suppression comment support (`# ast-skip:`)
- **comprehensive_field_validator.py** - Extended field validation with broader pattern recognition

## Usage

### Running Comprehensive Validation Suite
```bash
# Run all validators with unified reporting
python scripts/validation/framework/validation_suite_runner.py

# Advanced orchestration with caching
python scripts/validation/framework/unified_validation_engine.py --pre-commit
```

### Using as Libraries
```python
# Import validation framework
from scripts.validation.framework.validation_framework import BaseValidator

# Import AST analyzer
from scripts.validation.framework.ast_field_analyzer import ASTFieldAnalyzer

# Import configuration
from scripts.validation.framework.validation_config import ValidationConfig
```

## Architecture

The framework validators provide:
- **Orchestration**: Coordinate multiple validators for comprehensive checks
- **Configuration**: Centralized configuration management
- **Base Classes**: Common validation patterns for building new validators
- **Analysis Engine**: Core AST analysis capabilities with suppression support

## Integration Points

Framework validators are used by:
- Production validators for base functionality
- Pre-commit hooks for orchestration
- CI/CD pipelines for comprehensive validation
- Custom validators as base classes

## Documentation

See `docs/validation_tool_inventory.md` for detailed framework architecture and integration patterns.
