# AST Field Analyzer

## Current Setup

- **ast_field_analyzer.py** - The improved analyzer with file path inference (DEFAULT)
- **ast_field_analyzer_original.py** - The original analyzer (ARCHIVED)

## What Changed

The analyzer was improved to eliminate false positives in hook files by adding file path-based DocType inference. This reduced false positives by 6.8% (8 issues in membership_dues_schedule_hooks.py).

## Usage

```python
from ast_field_analyzer import ASTFieldAnalyzer

analyzer = ASTFieldAnalyzer(app_path)
issues = analyzer.validate_file(file_path)
```

## Testing

To compare the original vs improved analyzer:
```bash
python compare_analyzers.py
```

To test on a specific file:
```bash
python ast_field_analyzer.py path/to/file.py
```

## Key Improvement

Hook files (files ending with `_hooks.py`) now correctly infer their associated DocType from the file name pattern, eliminating false positives where the analyzer incorrectly assumed `doc` parameters were Member objects.