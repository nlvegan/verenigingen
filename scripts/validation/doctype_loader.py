#!/usr/bin/env python3
"""
Comprehensive DocType Loader for Field Validation

This centralized DocType loader addresses critical issues in the validation infrastructure:

1. Loads DocTypes from ALL installed apps (frappe, erpnext, payments, verenigingen)
2. Includes ALL fields: standard fields, custom fields, child table fields
3. Builds complete parent-child table relationship mapping
4. Provides caching for performance
5. Handles field metadata (fieldtype, options, etc.)
6. Validates DocType definitions for completeness

Key Features:
- Multi-app DocType loading
- Custom field integration
- Child table relationship mapping
- Metadata caching with TTL
- Field existence validation
- Performance optimized
- Error handling and logging
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Union, Any
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FieldType(Enum):
    """Standard Frappe field types"""
    DATA = "Data"
    TEXT = "Text"
    LONG_TEXT = "Long Text"
    HTML_EDITOR = "HTML Editor"
    MARKDOWN_EDITOR = "Markdown Editor"
    INT = "Int"
    FLOAT = "Float"
    CURRENCY = "Currency"
    PERCENT = "Percent"
    CHECK = "Check"
    SELECT = "Select"
    LINK = "Link"
    DYNAMIC_LINK = "Dynamic Link"
    PASSWORD = "Password"
    READ_ONLY = "Read Only"
    ATTACH = "Attach"
    ATTACH_IMAGE = "Attach Image"
    DATE = "Date"
    DATETIME = "Datetime"
    TIME = "Time"
    TABLE = "Table"
    TABLE_MULTISELECT = "Table MultiSelect"
    CODE = "Code"
    TEXT_EDITOR = "Text Editor"
    SIGNATURE = "Signature"
    RATING = "Rating"
    ICON = "Icon"
    GEOLOCATION = "Geolocation"
    JSON = "JSON"
    DURATION = "Duration"
    BARCODE = "Barcode"
    AUTOCOMPLETE = "Autocomplete"


@dataclass
class FieldMetadata:
    """Complete field metadata"""
    fieldname: str
    fieldtype: str
    label: Optional[str] = None
    options: Optional[str] = None
    reqd: bool = False
    unique: bool = False
    read_only: bool = False
    hidden: bool = False
    in_list_view: bool = False
    in_standard_filter: bool = False
    is_custom: bool = False
    parent_doctype: Optional[str] = None
    child_table_options: Optional[str] = None
    raw_data: Dict = dataclass_field(default_factory=dict)


@dataclass
class DocTypeMetadata:
    """Complete DocType metadata"""
    name: str
    app: str
    module: Optional[str] = None
    istable: bool = False
    issingle: bool = False
    is_submittable: bool = False
    is_tree: bool = False
    autoname: Optional[str] = None
    fields: Dict[str, FieldMetadata] = dataclass_field(default_factory=dict)
    child_tables: List[Tuple[str, str]] = dataclass_field(default_factory=list)  # (field_name, child_doctype)
    parent_doctypes: Set[str] = dataclass_field(default_factory=set)  # DocTypes that reference this as child
    permissions: List[Dict] = dataclass_field(default_factory=list)
    json_file_path: Optional[str] = None
    custom_fields: Dict[str, FieldMetadata] = dataclass_field(default_factory=dict)


@dataclass
class LoadingStats:
    """DocType loading statistics"""
    total_doctypes: int = 0
    total_fields: int = 0
    custom_fields: int = 0
    child_table_relationships: int = 0
    apps_scanned: Set[str] = dataclass_field(default_factory=set)
    load_time: float = 0.0
    errors: List[str] = dataclass_field(default_factory=list)


class DocTypeLoader:
    """Comprehensive DocType loader with caching and multi-app support"""
    
    def __init__(self, bench_path: str, cache_ttl: int = 3600, verbose: bool = False):
        """
        Initialize DocType loader
        
        Args:
            bench_path: Path to frappe-bench directory
            cache_ttl: Cache time-to-live in seconds (default 1 hour)
            verbose: Enable verbose logging
        """
        self.bench_path = Path(bench_path)
        self.apps_path = self.bench_path / "apps"
        self.cache_ttl = cache_ttl
        self.verbose = verbose
        
        # Cache
        self._cache_data: Optional[Dict[str, DocTypeMetadata]] = None
        self._cache_timestamp: float = 0
        self._child_table_mapping: Optional[Dict[str, str]] = None
        self._field_index: Optional[Dict[str, Set[str]]] = None  # fieldname -> set of doctypes that have it
        
        # Standard Frappe fields that exist on all DocTypes
        self.standard_fields = {
            'name': FieldMetadata('name', 'Link', 'Name'),
            'creation': FieldMetadata('creation', 'Datetime', 'Created On'),
            'modified': FieldMetadata('modified', 'Datetime', 'Last Modified'),
            'modified_by': FieldMetadata('modified_by', 'Link', 'Modified By', options='User'),
            'owner': FieldMetadata('owner', 'Link', 'Owner', options='User'),
            'docstatus': FieldMetadata('docstatus', 'Int', 'Document Status'),
            'parent': FieldMetadata('parent', 'Data', 'Parent'),
            'parentfield': FieldMetadata('parentfield', 'Data', 'Parent Field'),
            'parenttype': FieldMetadata('parenttype', 'Data', 'Parent Type'),
            'idx': FieldMetadata('idx', 'Int', 'Index'),
            'doctype': FieldMetadata('doctype', 'Data', 'Document Type'),
            '_user_tags': FieldMetadata('_user_tags', 'Data', 'User Tags'),
            '_comments': FieldMetadata('_comments', 'Text', 'Comments'),
            '_assign': FieldMetadata('_assign', 'Text', 'Assigned To'),
            '_liked_by': FieldMetadata('_liked_by', 'Text', 'Liked By'),
        }
        
        # Apps to scan (discover dynamically from apps directory)
        self.standard_apps = self._discover_installed_apps()
        
    def _discover_installed_apps(self) -> List[str]:
        """Discover all installed apps from the apps directory"""
        apps = []
        try:
            if self.apps_path.exists():
                for app_dir in self.apps_path.iterdir():
                    if (app_dir.is_dir() and 
                        not app_dir.name.startswith('.') and
                        (app_dir / 'pyproject.toml').exists()):
                        apps.append(app_dir.name)
            
            # Sort to ensure consistent ordering (frappe first, then alphabetical)
            apps.sort(key=lambda x: (x != 'frappe', x))
            
            if self.verbose:
                logger.info(f"Discovered apps: {apps}")
            
        except Exception as e:
            # Fallback to standard apps if discovery fails
            if self.verbose:
                logger.warning(f"Failed to discover apps, using fallback: {e}")
            apps = ['frappe', 'erpnext', 'payments', 'vereinigingen']
        
        return apps
        
    def get_doctypes(self, reload_cache: bool = False) -> Dict[str, DocTypeMetadata]:
        """
        Get all DocTypes, using cache if available
        
        Args:
            reload_cache: Force reload of cache
            
        Returns:
            Dictionary of DocType name -> DocTypeMetadata
        """
        current_time = time.time()
        
        if (self._cache_data is None or 
            reload_cache or 
            (current_time - self._cache_timestamp) > self.cache_ttl):
            
            if self.verbose:
                logger.info("Loading DocTypes from file system...")
            
            self._cache_data = self._load_all_doctypes()
            self._cache_timestamp = current_time
            self._child_table_mapping = None  # Reset derived data
            self._field_index = None
        
        return self._cache_data
    
    def get_doctype(self, doctype_name: str) -> Optional[DocTypeMetadata]:
        """Get metadata for a specific DocType"""
        doctypes = self.get_doctypes()
        return doctypes.get(doctype_name)
    
    def get_fields(self, doctype_name: str) -> Dict[str, FieldMetadata]:
        """Get all fields for a DocType (including standard and custom fields)"""
        doctype_meta = self.get_doctype(doctype_name)
        if not doctype_meta:
            return {}
        
        all_fields = {}
        all_fields.update(doctype_meta.fields)
        all_fields.update(doctype_meta.custom_fields)
        
        return all_fields
    
    def get_field_names(self, doctype_name: str) -> Set[str]:
        """Get all field names for a DocType"""
        fields = self.get_fields(doctype_name)
        return set(fields.keys())
    
    def has_field(self, doctype_name: str, field_name: str) -> bool:
        """Check if a DocType has a specific field"""
        field_names = self.get_field_names(doctype_name)
        return field_name in field_names
    
    def get_child_table_mapping(self) -> Dict[str, str]:
        """
        Get mapping of parent_doctype.field_name -> child_doctype
        
        Returns:
            Dictionary mapping parent field references to child DocTypes
        """
        if self._child_table_mapping is None:
            self._child_table_mapping = self._build_child_table_mapping()
        
        return self._child_table_mapping
    
    def get_field_index(self) -> Dict[str, Set[str]]:
        """
        Get index of field names to DocTypes that contain them
        
        Returns:
            Dictionary of field_name -> set of DocType names that have this field
        """
        if self._field_index is None:
            self._field_index = self._build_field_index()
        
        return self._field_index
    
    def find_doctypes_with_field(self, field_name: str) -> Set[str]:
        """Find all DocTypes that contain a specific field"""
        field_index = self.get_field_index()
        return field_index.get(field_name, set())
    
    def get_loading_stats(self) -> LoadingStats:
        """Get statistics about the last loading operation"""
        doctypes = self.get_doctypes()
        
        stats = LoadingStats()
        stats.total_doctypes = len(doctypes)
        
        for doctype_meta in doctypes.values():
            stats.total_fields += len(doctype_meta.fields)
            stats.custom_fields += len(doctype_meta.custom_fields)
            stats.child_table_relationships += len(doctype_meta.child_tables)
            stats.apps_scanned.add(doctype_meta.app)
        
        return stats
    
    # Convenience methods for legacy validator compatibility
    
    def get_doctypes_simple(self) -> Dict[str, Set[str]]:
        """
        Get DocTypes in simple format for legacy validators
        
        Returns:
            Dictionary of DocType name -> Set of field names
        """
        result = {}
        doctypes = self.get_doctypes()
        
        for doctype_name, doctype_meta in doctypes.items():
            field_names = self.get_field_names(doctype_name)
            result[doctype_name] = field_names
        
        return result
    
    def get_doctypes_detailed(self) -> Dict[str, Dict]:
        """
        Get DocTypes in detailed format for advanced validators
        
        Returns:
            Dictionary with detailed DocType information including metadata
        """
        result = {}
        doctypes = self.get_doctypes()
        
        for doctype_name, doctype_meta in doctypes.items():
            field_names = self.get_field_names(doctype_name)
            
            result[doctype_name] = {
                'fields': field_names,
                'data': {
                    'name': doctype_name,
                    'app': doctype_meta.app,
                    'istable': doctype_meta.istable,
                    'issingle': doctype_meta.issingle,
                    'is_submittable': doctype_meta.is_submittable,
                    'is_tree': doctype_meta.is_tree,
                    'autoname': doctype_meta.autoname,
                    'module': doctype_meta.module,
                    'permissions': doctype_meta.permissions
                },
                'app': doctype_meta.app,
                'child_tables': doctype_meta.child_tables,
                'parent_doctypes': list(doctype_meta.parent_doctypes),
                'file': doctype_meta.json_file_path,
                'custom_fields_count': len(doctype_meta.custom_fields)
            }
        
        return result
    
    def load_from_single_app(self, app_name: str) -> Dict[str, Set[str]]:
        """
        Load DocTypes from a single app only (for specific validators)
        
        Args:
            app_name: Name of the app to load from
            
        Returns:
            Dictionary of DocType name -> Set of field names
        """
        app_path = self.apps_path / app_name
        if not app_path.exists():
            if self.verbose:
                logger.warning(f"App '{app_name}' not found at {app_path}")
            return {}
        
        app_doctypes = self._load_doctypes_from_app(app_path, app_name)
        
        # Convert to simple format
        result = {}
        for doctype_name, doctype_meta in app_doctypes.items():
            # Add standard fields
            fields = set(self.standard_fields.keys())
            # Add defined fields
            fields.update(doctype_meta.fields.keys())
            result[doctype_name] = fields
        
        return result
    
    def validate_doctype_completeness(self, doctype_name: str) -> List[str]:
        """Validate that a DocType is properly loaded with all expected fields"""
        issues = []
        
        doctype_meta = self.get_doctype(doctype_name)
        if not doctype_meta:
            issues.append(f"DocType '{doctype_name}' not found")
            return issues
        
        # Check for standard fields
        for std_field_name in self.standard_fields:
            if std_field_name not in doctype_meta.fields:
                issues.append(f"Missing standard field '{std_field_name}' in {doctype_name}")
        
        # Check for required metadata
        if not doctype_meta.app:
            issues.append(f"Missing app information for {doctype_name}")
        
        if not doctype_meta.json_file_path:
            issues.append(f"Missing JSON file path for {doctype_name}")
        
        return issues
    
    def _load_all_doctypes(self) -> Dict[str, DocTypeMetadata]:
        """Load DocTypes from all apps"""
        start_time = time.time()
        doctypes = {}
        
        # First, load standard fields for all DocTypes
        for app_name in self.standard_apps:
            app_path = self.apps_path / app_name
            if app_path.exists():
                if self.verbose:
                    logger.info(f"Loading DocTypes from {app_name}...")
                
                app_doctypes = self._load_doctypes_from_app(app_path, app_name)
                doctypes.update(app_doctypes)
        
        # Then, load custom fields
        self._load_custom_fields(doctypes)
        
        # Build relationships
        self._build_relationships(doctypes)
        
        load_time = time.time() - start_time
        
        if self.verbose:
            stats = LoadingStats()
            stats.total_doctypes = len(doctypes)
            for doctype_meta in doctypes.values():
                stats.total_fields += len(doctype_meta.fields)
                stats.custom_fields += len(doctype_meta.custom_fields)
            
            logger.info(f"Loaded {stats.total_doctypes} DocTypes with {stats.total_fields} fields "
                       f"({stats.custom_fields} custom) in {load_time:.2f}s")
        
        return doctypes
    
    def _load_doctypes_from_app(self, app_path: Path, app_name: str) -> Dict[str, DocTypeMetadata]:
        """Load all DocTypes from a specific app"""
        doctypes = {}
        
        # Find all DocType JSON files
        for json_file in app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    doctype_meta = self._load_doctype_from_file(json_file, app_name)
                    if doctype_meta:
                        doctypes[doctype_meta.name] = doctype_meta
                        
                except Exception as e:
                    if self.verbose:
                        logger.warning(f"Error loading {json_file}: {e}")
        
        return doctypes
    
    def _load_doctype_from_file(self, json_file: Path, app_name: str) -> Optional[DocTypeMetadata]:
        """Load a single DocType from its JSON file"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            doctype_name = data.get('name')
            if not doctype_name:
                return None
            
            # Create DocType metadata
            doctype_meta = DocTypeMetadata(
                name=doctype_name,
                app=app_name,
                module=data.get('module'),
                istable=data.get('istable', 0) == 1,
                issingle=data.get('issingle', 0) == 1,
                is_submittable=data.get('is_submittable', 0) == 1,
                is_tree=data.get('is_tree', 0) == 1,
                autoname=data.get('autoname'),
                json_file_path=str(json_file),
                permissions=data.get('permissions', [])
            )
            
            # Add standard fields first
            for std_field_name, std_field_meta in self.standard_fields.items():
                field_copy = FieldMetadata(
                    fieldname=std_field_meta.fieldname,
                    fieldtype=std_field_meta.fieldtype,
                    label=std_field_meta.label,
                    options=std_field_meta.options,
                    parent_doctype=doctype_name
                )
                doctype_meta.fields[std_field_name] = field_copy
            
            # Load defined fields
            for field_data in data.get('fields', []):
                field_meta = self._create_field_metadata(field_data, doctype_name)
                if field_meta:
                    doctype_meta.fields[field_meta.fieldname] = field_meta
                    
                    # Track child table relationships
                    if field_data.get('fieldtype') == 'Table':
                        child_doctype = field_data.get('options')
                        if child_doctype:
                            doctype_meta.child_tables.append((field_meta.fieldname, child_doctype))
            
            return doctype_meta
            
        except Exception as e:
            if self.verbose:
                logger.error(f"Failed to load DocType from {json_file}: {e}")
            return None
    
    def _create_field_metadata(self, field_data: Dict, parent_doctype: str) -> Optional[FieldMetadata]:
        """Create FieldMetadata from field definition"""
        fieldname = field_data.get('fieldname')
        if not fieldname:
            return None
        
        field_meta = FieldMetadata(
            fieldname=fieldname,
            fieldtype=field_data.get('fieldtype', 'Data'),
            label=field_data.get('label'),
            options=field_data.get('options'),
            reqd=field_data.get('reqd', 0) == 1,
            unique=field_data.get('unique', 0) == 1,
            read_only=field_data.get('read_only', 0) == 1,
            hidden=field_data.get('hidden', 0) == 1,
            in_list_view=field_data.get('in_list_view', 0) == 1,
            in_standard_filter=field_data.get('in_standard_filter', 0) == 1,
            parent_doctype=parent_doctype,
            raw_data=field_data.copy()
        )
        
        # Set child table options
        if field_meta.fieldtype == 'Table':
            field_meta.child_table_options = field_data.get('options')
        
        return field_meta
    
    def _load_custom_fields(self, doctypes: Dict[str, DocTypeMetadata]):
        """Load custom fields for all DocTypes from fixture files"""
        custom_fields_loaded = 0
        
        for app_name in self.standard_apps:
            app_path = self.apps_path / app_name
            if not app_path.exists():
                continue
            
            # Look for custom field fixture files
            custom_field_fixtures = list(app_path.rglob("**/custom_field.json"))
            
            for fixture_file in custom_field_fixtures:
                try:
                    fields_added = self._load_custom_fields_from_fixture(fixture_file, doctypes)
                    custom_fields_loaded += fields_added
                    
                    if self.verbose and fields_added > 0:
                        logger.info(f"Loaded {fields_added} custom fields from {fixture_file}")
                        
                except Exception as e:
                    if self.verbose:
                        logger.warning(f"Error loading custom fields from {fixture_file}: {e}")
        
        if self.verbose and custom_fields_loaded > 0:
            logger.info(f"Total custom fields loaded: {custom_fields_loaded}")
    
    def _load_custom_fields_from_fixture(self, fixture_file: Path, doctypes: Dict[str, DocTypeMetadata]) -> int:
        """Load custom fields from a fixture file"""
        fields_added = 0
        
        try:
            with open(fixture_file, 'r', encoding='utf-8') as f:
                fixture_data = json.load(f)
            
            if not isinstance(fixture_data, list):
                return 0
            
            for custom_field_data in fixture_data:
                if not isinstance(custom_field_data, dict):
                    continue
                
                # Validate this is a Custom Field entry
                if custom_field_data.get('doctype') != 'Custom Field':
                    continue
                
                # Get target DocType and field info
                target_doctype = custom_field_data.get('dt')
                fieldname = custom_field_data.get('fieldname')
                
                if not target_doctype or not fieldname:
                    continue
                
                # Check if target DocType exists in our loaded DocTypes
                if target_doctype not in doctypes:
                    if self.verbose:
                        logger.warning(f"Custom field {fieldname} targets unknown DocType {target_doctype}")
                    continue
                
                # Create FieldMetadata for this custom field
                custom_field_meta = FieldMetadata(
                    fieldname=fieldname,
                    fieldtype=custom_field_data.get('fieldtype', 'Data'),
                    label=custom_field_data.get('label'),
                    options=custom_field_data.get('options'),
                    reqd=custom_field_data.get('reqd', 0) == 1,
                    unique=custom_field_data.get('unique', 0) == 1,
                    read_only=custom_field_data.get('read_only', 0) == 1,
                    hidden=custom_field_data.get('hidden', 0) == 1,
                    in_list_view=custom_field_data.get('in_list_view', 0) == 1,
                    in_standard_filter=custom_field_data.get('in_standard_filter', 0) == 1,
                    is_custom=True,
                    parent_doctype=target_doctype,
                    raw_data=custom_field_data.copy()
                )
                
                # Add to the target DocType's custom_fields
                doctypes[target_doctype].custom_fields[fieldname] = custom_field_meta
                fields_added += 1
                
                if self.verbose:
                    logger.debug(f"Added custom field {fieldname} to {target_doctype}")
        
        except Exception as e:
            if self.verbose:
                logger.error(f"Failed to parse custom field fixture {fixture_file}: {e}")
            raise
        
        return fields_added
    
    def _build_relationships(self, doctypes: Dict[str, DocTypeMetadata]):
        """Build parent-child relationships between DocTypes"""
        for doctype_name, doctype_meta in doctypes.items():
            for field_name, child_doctype_name in doctype_meta.child_tables:
                if child_doctype_name in doctypes:
                    doctypes[child_doctype_name].parent_doctypes.add(doctype_name)
    
    def _build_child_table_mapping(self) -> Dict[str, str]:
        """Build mapping of parent.field -> child_doctype"""
        mapping = {}
        doctypes = self.get_doctypes()
        
        for doctype_name, doctype_meta in doctypes.items():
            for field_name, child_doctype_name in doctype_meta.child_tables:
                key = f"{doctype_name}.{field_name}"
                mapping[key] = child_doctype_name
        
        return mapping
    
    def _build_field_index(self) -> Dict[str, Set[str]]:
        """Build index of field names to DocTypes"""
        field_index = {}
        doctypes = self.get_doctypes()
        
        for doctype_name, doctype_meta in doctypes.items():
            # Index regular fields
            for field_name in doctype_meta.fields:
                if field_name not in field_index:
                    field_index[field_name] = set()
                field_index[field_name].add(doctype_name)
            
            # Index custom fields
            for field_name in doctype_meta.custom_fields:
                if field_name not in field_index:
                    field_index[field_name] = set()
                field_index[field_name].add(doctype_name)
        
        return field_index


# Convenience factory functions for easy validator integration

def get_unified_doctype_loader(app_path: str, verbose: bool = False) -> DocTypeLoader:
    """
    Factory function to create a unified DocType loader for validation tools
    
    Args:
        app_path: Path to the app (will derive bench_path automatically)
        verbose: Enable verbose logging
        
    Returns:
        Configured DocTypeLoader instance
    """
    if isinstance(app_path, str):
        app_path = Path(app_path)
    
    # Derive bench path from app path
    bench_path = app_path.parent.parent
    
    return DocTypeLoader(str(bench_path), verbose=verbose)


def load_doctypes_simple(app_path: str, verbose: bool = False) -> Dict[str, Set[str]]:
    """
    Quick convenience function for validators that need simple DocType -> fields mapping
    
    Args:
        app_path: Path to the app
        verbose: Enable verbose logging
        
    Returns:
        Dictionary of DocType name -> Set of field names
    """
    loader = get_unified_doctype_loader(app_path, verbose)
    return loader.get_doctypes_simple()


def load_doctypes_detailed(app_path: str, verbose: bool = False) -> Dict[str, Dict]:
    """
    Quick convenience function for validators that need detailed DocType information
    
    Args:
        app_path: Path to the app
        verbose: Enable verbose logging
        
    Returns:
        Dictionary with detailed DocType information
    """
    loader = get_unified_doctype_loader(app_path, verbose)
    return loader.get_doctypes_detailed()


def main():
    """Test the DocType loader"""
    import sys
    
    bench_path = "/home/frappe/frappe-bench"
    if len(sys.argv) > 1:
        bench_path = sys.argv[1]
    
    loader = DocTypeLoader(bench_path, verbose=True)
    
    print("🔍 Testing comprehensive DocType loader...")
    print("=" * 60)
    
    # Load DocTypes
    start_time = time.time()
    doctypes = loader.get_doctypes()
    load_time = time.time() - start_time
    
    # Show statistics
    stats = loader.get_loading_stats()
    print(f"📊 Loading Statistics:")
    print(f"   DocTypes: {stats.total_doctypes}")
    print(f"   Fields: {stats.total_fields}")
    print(f"   Custom Fields: {stats.custom_fields}")
    print(f"   Child Table Relationships: {stats.child_table_relationships}")
    print(f"   Apps: {', '.join(sorted(stats.apps_scanned))}")
    print(f"   Load Time: {load_time:.2f}s")
    print()
    
    # Test specific DocTypes
    test_doctypes = ['Member', 'Sales Invoice', 'User', 'Verenigingen Volunteer', 'Chapter']
    
    print("🧪 Testing specific DocTypes:")
    for doctype_name in test_doctypes:
        doctype_meta = loader.get_doctype(doctype_name)
        if doctype_meta:
            fields = loader.get_field_names(doctype_name)
            child_tables = len(doctype_meta.child_tables)
            print(f"   ✅ {doctype_name}: {len(fields)} fields, {child_tables} child tables ({doctype_meta.app})")
            
            # Show some sample fields
            field_names = list(fields)[:5]
            print(f"      Sample fields: {', '.join(field_names)}")
        else:
            print(f"   ❌ {doctype_name}: Not found")
    print()
    
    # Test child table mapping
    child_mapping = loader.get_child_table_mapping()
    print(f"🔗 Child Table Relationships: {len(child_mapping)}")
    
    # Show some examples
    for key, value in list(child_mapping.items())[:5]:
        print(f"   {key} -> {value}")
    
    if len(child_mapping) > 5:
        print(f"   ... and {len(child_mapping) - 5} more relationships")
    print()
    
    # Test field index
    field_index = loader.get_field_index()
    print(f"🗂️ Field Index: {len(field_index)} unique field names")
    
    # Test some common fields
    common_fields = ['name', 'member', 'customer', 'posting_date', 'amount']
    for field_name in common_fields:
        doctypes_with_field = loader.find_doctypes_with_field(field_name)
        if doctypes_with_field:
            print(f"   '{field_name}' found in {len(doctypes_with_field)} DocTypes")
        else:
            print(f"   '{field_name}' not found in any DocType")
    
    print()
    print("✅ DocType loader test completed successfully!")
    
    return 0


if __name__ == "__main__":
    exit(main())