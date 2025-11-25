#!/usr/bin/env python3
"""
Validation Configuration System

Provides flexible configuration for the schema-aware validator with different
validation levels and customizable patterns.
"""

import json
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class ValidationLevel(Enum):
    """Validation strictness levels"""
    STRICT = "strict"           # High confidence threshold, minimal exclusions
    BALANCED = "balanced"       # Balanced accuracy vs false positives  
    PERMISSIVE = "permissive"   # Low confidence threshold, many exclusions
    CUSTOM = "custom"           # User-defined configuration


@dataclass
class ConfidenceThresholds:
    """Confidence thresholds for different validation aspects"""
    field_access: float = 0.8      # Minimum confidence for field access validation
    sql_context: float = 0.6       # Confidence reduction for SQL context
    api_context: float = 0.4       # Confidence reduction for API results
    child_table: float = 0.9       # Confidence for child table validation
    property_method: float = 0.7   # Confidence for property method detection


@dataclass 
class ExclusionPatterns:
    """Patterns to exclude from validation"""
    # Object names to always skip
    skip_objects: Set[str] = field(default_factory=lambda: {
        'frappe', 'self', 'cls', 'request', 'response', 'form_dict',
        'local', 'cache', 'session', 'user', 'db', 'utils', 'json',
        'datetime', 'date', 'time', 're', 'os', 'sys', 'math'
    })
    
    # Field names that are commonly valid across contexts
    common_fields: Set[str] = field(default_factory=lambda: {
        'name', 'title', 'status', 'owner', 'creation', 'modified',
        'modified_by', 'docstatus', 'idx', 'parent', 'parenttype',
        'parentfield', '__dict__', '__class__', '__module__'
    })
    
    # SQL alias patterns that are commonly used
    sql_aliases: Set[str] = field(default_factory=lambda: {
        'total', 'count', 'sum', 'avg', 'min', 'max', 'id', 'code',
        'amount', 'date', 'type', 'category', 'reference', 'description'
    })
    
    # Property method patterns
    property_patterns: List[str] = field(default_factory=lambda: [
        r'@property',
        r'def\s+\w+\(self\)\s*:',
        r'return\s+self\._\w+',
    ])
    
    # Child table field patterns
    child_table_fields: Set[str] = field(default_factory=lambda: {
        'team_members', 'board_members', 'chapter_members', 'roles',
        'items', 'entries', 'lines', 'details', 'memberships'
    })
    
    # File patterns to skip entirely
    skip_file_patterns: List[str] = field(default_factory=lambda: [
        '__pycache__', '.git', 'node_modules', '.pyc', 'test_validation',
        'validator', 'validation', '/migrations/', '/patches/'
    ])


@dataclass
class ValidationRules:
    """Specific validation rules and behaviors"""
    # Enable/disable specific validation types
    validate_field_access: bool = True
    validate_sql_queries: bool = True
    validate_child_tables: bool = True
    validate_property_methods: bool = True
    validate_api_calls: bool = True
    
    # Context analysis settings
    context_radius: int = 5         # Lines of context to analyze
    max_confidence: float = 1.0     # Maximum confidence score
    min_confidence: float = 0.1     # Minimum confidence score
    
    # Performance settings
    max_files_to_process: int = 10000
    enable_caching: bool = True
    parallel_processing: bool = False


@dataclass
class ReportingConfig:
    """Configuration for validation reporting"""
    max_issues_per_file: int = 50
    max_suggestions: int = 3
    group_by_confidence: bool = True
    show_context: bool = True
    show_suggestions: bool = True
    verbose_output: bool = False
    
    # Output formats
    output_format: str = "text"  # text, json, csv
    include_statistics: bool = True
    include_file_summary: bool = True


@dataclass
class ValidationConfig:
    """Complete validation configuration"""
    level: ValidationLevel = ValidationLevel.BALANCED
    confidence_thresholds: ConfidenceThresholds = field(default_factory=ConfidenceThresholds)
    exclusion_patterns: ExclusionPatterns = field(default_factory=ExclusionPatterns)
    validation_rules: ValidationRules = field(default_factory=ValidationRules)
    reporting_config: ReportingConfig = field(default_factory=ReportingConfig)
    
    # Custom overrides
    custom_doctypes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    custom_field_mappings: Dict[str, str] = field(default_factory=dict)


class ConfigurationManager:
    """Manages validation configuration loading and saving"""
    
    DEFAULT_CONFIG_FILE = "validation_config.json"
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(__file__).parent
        self.config_file = self.config_dir / self.DEFAULT_CONFIG_FILE
        self._presets = self._build_presets()
    
    def _build_presets(self) -> Dict[str, ValidationConfig]:
        """Build preset configurations"""
        presets = {}
        
        # Strict configuration - minimal false positives
        strict_confidence = ConfidenceThresholds(
            field_access=0.95,
            sql_context=0.8,
            api_context=0.6,
            child_table=0.95,
            property_method=0.9
        )
        
        strict_exclusions = ExclusionPatterns()
        strict_exclusions.skip_objects = {
            'frappe', 'self', 'cls'  # Minimal exclusions
        }
        
        presets[ValidationLevel.STRICT.value] = ValidationConfig(
            level=ValidationLevel.STRICT,
            confidence_thresholds=strict_confidence,
            exclusion_patterns=strict_exclusions
        )
        
        # Balanced configuration - good balance
        balanced_confidence = ConfidenceThresholds(
            field_access=0.8,
            sql_context=0.6,
            api_context=0.4,
            child_table=0.9,
            property_method=0.7
        )
        
        presets[ValidationLevel.BALANCED.value] = ValidationConfig(
            level=ValidationLevel.BALANCED,
            confidence_thresholds=balanced_confidence,
            exclusion_patterns=ExclusionPatterns()  # Default exclusions
        )
        
        # Permissive configuration - fewer false positives
        permissive_confidence = ConfidenceThresholds(
            field_access=0.6,
            sql_context=0.4,
            api_context=0.2,
            child_table=0.8,
            property_method=0.5
        )
        
        permissive_exclusions = ExclusionPatterns()
        # Add more exclusions for permissive mode
        permissive_exclusions.skip_objects.update({
            'data', 'result', 'response', 'item', 'obj', 'doc', 'record',
            'entry', 'row', 'args', 'kwargs', 'params', 'config'
        })
        
        presets[ValidationLevel.PERMISSIVE.value] = ValidationConfig(
            level=ValidationLevel.PERMISSIVE,
            confidence_thresholds=permissive_confidence,
            exclusion_patterns=permissive_exclusions
        )
        
        return presets
    
    def get_preset_config(self, level: ValidationLevel) -> ValidationConfig:
        """Get a preset configuration"""
        return self._presets.get(level.value, self._presets[ValidationLevel.BALANCED.value])
    
    def load_config(self, config_path: Optional[Path] = None) -> ValidationConfig:
        """Load configuration from file"""
        config_file = config_path or self.config_file
        
        if not config_file.exists():
            # Return default balanced configuration
            return self.get_preset_config(ValidationLevel.BALANCED)
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Convert to configuration object
            config = self._dict_to_config(data)
            return config
            
        except Exception as e:
            print(f"⚠️  Error loading config from {config_file}: {e}")
            print("   Using default balanced configuration")
            return self.get_preset_config(ValidationLevel.BALANCED)
    
    def save_config(self, config: ValidationConfig, config_path: Optional[Path] = None):
        """Save configuration to file"""
        config_file = config_path or self.config_file
        
        try:
            # Convert to dictionary
            data = self._config_to_dict(config)
            
            # Ensure directory exists
            config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            
            print(f"✅ Configuration saved to {config_file}")
            
        except Exception as e:
            print(f"❌ Error saving config to {config_file}: {e}")
    
    def _dict_to_config(self, data: Dict[str, Any]) -> ValidationConfig:
        """Convert dictionary to ValidationConfig"""
        # Handle level
        level_str = data.get('level', 'balanced')
        try:
            level = ValidationLevel(level_str)
        except ValueError:
            level = ValidationLevel.BALANCED
        
        # Build confidence thresholds
        confidence_data = data.get('confidence_thresholds', {})
        confidence = ConfidenceThresholds(
            field_access=confidence_data.get('field_access', 0.8),
            sql_context=confidence_data.get('sql_context', 0.6),
            api_context=confidence_data.get('api_context', 0.4),
            child_table=confidence_data.get('child_table', 0.9),
            property_method=confidence_data.get('property_method', 0.7)
        )
        
        # Build exclusion patterns
        exclusion_data = data.get('exclusion_patterns', {})
        exclusions = ExclusionPatterns(
            skip_objects=set(exclusion_data.get('skip_objects', [])),
            common_fields=set(exclusion_data.get('common_fields', [])),
            sql_aliases=set(exclusion_data.get('sql_aliases', [])),
            property_patterns=exclusion_data.get('property_patterns', []),
            child_table_fields=set(exclusion_data.get('child_table_fields', [])),
            skip_file_patterns=exclusion_data.get('skip_file_patterns', [])
        )
        
        # Build validation rules
        rules_data = data.get('validation_rules', {})
        rules = ValidationRules(
            validate_field_access=rules_data.get('validate_field_access', True),
            validate_sql_queries=rules_data.get('validate_sql_queries', True),
            validate_child_tables=rules_data.get('validate_child_tables', True),
            validate_property_methods=rules_data.get('validate_property_methods', True),
            validate_api_calls=rules_data.get('validate_api_calls', True),
            context_radius=rules_data.get('context_radius', 5),
            max_confidence=rules_data.get('max_confidence', 1.0),
            min_confidence=rules_data.get('min_confidence', 0.1),
            max_files_to_process=rules_data.get('max_files_to_process', 10000),
            enable_caching=rules_data.get('enable_caching', True),
            parallel_processing=rules_data.get('parallel_processing', False)
        )
        
        # Build reporting config
        reporting_data = data.get('reporting_config', {})
        reporting = ReportingConfig(
            max_issues_per_file=reporting_data.get('max_issues_per_file', 50),
            max_suggestions=reporting_data.get('max_suggestions', 3),
            group_by_confidence=reporting_data.get('group_by_confidence', True),
            show_context=reporting_data.get('show_context', True),
            show_suggestions=reporting_data.get('show_suggestions', True),
            verbose_output=reporting_data.get('verbose_output', False),
            output_format=reporting_data.get('output_format', 'text'),
            include_statistics=reporting_data.get('include_statistics', True),
            include_file_summary=reporting_data.get('include_file_summary', True)
        )
        
        return ValidationConfig(
            level=level,
            confidence_thresholds=confidence,
            exclusion_patterns=exclusions,
            validation_rules=rules,
            reporting_config=reporting,
            custom_doctypes=data.get('custom_doctypes', {}),
            custom_field_mappings=data.get('custom_field_mappings', {})
        )
    
    def _config_to_dict(self, config: ValidationConfig) -> Dict[str, Any]:
        """Convert ValidationConfig to dictionary"""
        data = {
            'level': config.level.value,
            'confidence_thresholds': asdict(config.confidence_thresholds),
            'validation_rules': asdict(config.validation_rules),
            'reporting_config': asdict(config.reporting_config),
            'custom_doctypes': config.custom_doctypes,
            'custom_field_mappings': config.custom_field_mappings
        }
        
        # Handle exclusion patterns (sets need to be converted to lists)
        exclusions = config.exclusion_patterns
        data['exclusion_patterns'] = {
            'skip_objects': list(exclusions.skip_objects),
            'common_fields': list(exclusions.common_fields),
            'sql_aliases': list(exclusions.sql_aliases),
            'property_patterns': exclusions.property_patterns,
            'child_table_fields': list(exclusions.child_table_fields),
            'skip_file_patterns': exclusions.skip_file_patterns
        }
        
        return data
    
    def create_custom_config(self, base_level: ValidationLevel = ValidationLevel.BALANCED,
                           **overrides) -> ValidationConfig:
        """Create a custom configuration based on a preset"""
        config = self.get_preset_config(base_level)
        config.level = ValidationLevel.CUSTOM
        
        # Apply overrides
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)
            elif hasattr(config.confidence_thresholds, key):
                setattr(config.confidence_thresholds, key, value)
            elif hasattr(config.validation_rules, key):
                setattr(config.validation_rules, key, value)
            elif hasattr(config.reporting_config, key):
                setattr(config.reporting_config, key, value)
        
        return config
    
    def list_available_presets(self) -> List[str]:
        """List available configuration presets"""
        return list(self._presets.keys())
    
    def print_config_summary(self, config: ValidationConfig):
        """Print a summary of the configuration"""
        print(f"📋 Validation Configuration Summary")
        print(f"   Level: {config.level.value}")
        print(f"   Field Access Confidence: {config.confidence_thresholds.field_access:.1%}")
        print(f"   SQL Context Confidence: {config.confidence_thresholds.sql_context:.1%}")
        print(f"   Skip Objects: {len(config.exclusion_patterns.skip_objects)}")
        print(f"   Context Radius: {config.validation_rules.context_radius} lines")
        print(f"   Output Format: {config.reporting_config.output_format}")


def create_default_config_file():
    """Create a default configuration file"""
    config_manager = ConfigurationManager()
    default_config = config_manager.get_preset_config(ValidationLevel.BALANCED)
    config_manager.save_config(default_config)
    print("✅ Default configuration file created")


def main():
    """Configuration management CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Validation Configuration Manager')
    parser.add_argument('--create-default', action='store_true',
                       help='Create default configuration file')
    parser.add_argument('--list-presets', action='store_true',
                       help='List available configuration presets')
    parser.add_argument('--show-config', type=str,
                       help='Show configuration summary for preset')
    parser.add_argument('--config-dir', type=str,
                       help='Configuration directory')
    
    args = parser.parse_args()
    
    config_dir = Path(args.config_dir) if args.config_dir else None
    config_manager = ConfigurationManager(config_dir)
    
    if args.create_default:
        create_default_config_file()
    elif args.list_presets:
        presets = config_manager.list_available_presets()
        print("📋 Available Configuration Presets:")
        for preset in presets:
            print(f"   - {preset}")
    elif args.show_config:
        try:
            level = ValidationLevel(args.show_config)
            config = config_manager.get_preset_config(level)
            config_manager.print_config_summary(config)
        except ValueError:
            print(f"❌ Unknown preset: {args.show_config}")
            print("   Available presets:", config_manager.list_available_presets())
    else:
        # Default: show current configuration
        config = config_manager.load_config()
        config_manager.print_config_summary(config)


if __name__ == "__main__":
    main()