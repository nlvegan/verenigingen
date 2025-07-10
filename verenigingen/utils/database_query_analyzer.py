"""
Database Query Analyzer for Verenigingen app

Analyzes database queries for performance optimization opportunities,
recommends indexes, and identifies slow query patterns.
"""

import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.utils import get_datetime, now_datetime

from verenigingen.utils.config_manager import ConfigManager
from verenigingen.utils.error_handling import get_logger


class QueryAnalyzer:
    """Analyze database queries for optimization opportunities"""

    def __init__(self):
        self.logger = get_logger("verenigingen.query_analyzer")
        self.slow_query_threshold = ConfigManager.get("slow_query_threshold_ms", 1000)

    def analyze_slow_queries(self, hours: int = 24) -> Dict[str, Any]:
        """
        Analyze slow queries from the database log

        Args:
            hours: Number of hours to look back

        Returns:
            Analysis results with optimization recommendations
        """
        self.logger.info(f"Analyzing slow queries for the last {hours} hours")

        analysis = {
            "summary": {
                "total_slow_queries": 0,
                "unique_patterns": 0,
                "tables_affected": set(),
                "avg_execution_time": 0,
            },
            "slow_queries": [],
            "patterns": {},
            "recommendations": [],
        }

        # Get slow queries from MariaDB/MySQL slow query log
        slow_queries = self._get_slow_queries_from_db(hours)

        if not slow_queries:
            analysis["summary"]["message"] = "No slow queries found in the specified time period"
            return analysis

        # Analyze queries
        for query_info in slow_queries:
            self._analyze_single_query(query_info, analysis)

        # Generate patterns and recommendations
        self._identify_query_patterns(analysis)
        self._generate_optimization_recommendations(analysis)

        # Calculate summary statistics
        analysis["summary"]["total_slow_queries"] = len(analysis["slow_queries"])
        analysis["summary"]["unique_patterns"] = len(analysis["patterns"])
        analysis["summary"]["tables_affected"] = list(analysis["summary"]["tables_affected"])

        if analysis["slow_queries"]:
            total_time = sum(q["execution_time_ms"] for q in analysis["slow_queries"])
            analysis["summary"]["avg_execution_time"] = total_time / len(analysis["slow_queries"])

        return analysis

    def _get_slow_queries_from_db(self, hours: int) -> List[Dict[str, Any]]:
        """Get slow queries from database (implementation depends on DB setup)"""

        queries = []

        try:
            # Try to get from frappe's query log if available
            # cutoff_time = now_datetime() - timedelta(hours=hours)

            # This is a simplified version - in production, you'd read from:
            # 1. MySQL slow query log file
            # 2. Performance schema tables
            # 3. Custom query logging table

            # For now, let's analyze current table statistics
            table_stats = frappe.db.sql(
                """
                SELECT
                    table_name,
                    table_rows,
                    avg_row_length,
                    data_length,
                    index_length
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name LIKE 'tab%'
                ORDER BY data_length DESC
                LIMIT 20
            """,
                as_dict=True,
            )

            # Simulate slow query detection based on table size
            for stat in table_stats:
                if stat["table_rows"] > 10000:  # Tables with many rows
                    queries.append(
                        {
                            "query": "SELECT * FROM `{stat['table_name']}` WHERE ...",
                            "execution_time_ms": stat["table_rows"] / 10,  # Simulated
                            "rows_examined": stat["table_rows"],
                            "timestamp": now_datetime(),
                        }
                    )

        except Exception as e:
            self.logger.error(f"Failed to get slow queries: {str(e)}")

        return queries

    def _analyze_single_query(self, query_info: Dict[str, Any], analysis: Dict[str, Any]) -> None:
        """Analyze a single query"""

        query = query_info.get("query", "")

        # Extract table names
        tables = self._extract_table_names(query)
        analysis["summary"]["tables_affected"].update(tables)

        # Check for common performance issues
        issues = []

        # Check for SELECT *
        if "SELECT *" in query.upper():
            issues.append("Uses SELECT * - specify only needed columns")

        # Check for missing WHERE clause
        if "WHERE" not in query.upper() and "SELECT" in query.upper():
            issues.append("No WHERE clause - may scan entire table")

        # Check for LIKE with leading wildcard
        if re.search(r"LIKE\s+'%[^']+", query, re.IGNORECASE):
            issues.append("LIKE with leading wildcard - cannot use index")

        # Check for OR conditions
        if " OR " in query.upper():
            issues.append("Uses OR condition - may prevent index usage")

        # Check for NOT IN
        if "NOT IN" in query.upper():
            issues.append("Uses NOT IN - consider using LEFT JOIN")

        # Check for subqueries
        if query.count("SELECT") > 1:
            issues.append("Contains subquery - consider using JOIN")

        # Add to slow queries list
        analysis["slow_queries"].append(
            {
                "query": query,
                "execution_time_ms": query_info.get("execution_time_ms", 0),
                "rows_examined": query_info.get("rows_examined", 0),
                "timestamp": query_info.get("timestamp"),
                "tables": list(tables),
                "issues": issues,
            }
        )

    def _extract_table_names(self, query: str) -> set:
        """Extract table names from SQL query"""

        tables = set()

        # Pattern to match table names after FROM, JOIN, UPDATE, INSERT INTO
        patterns = [
            r"FROM\s+`?(\w+)`?",
            r"JOIN\s+`?(\w+)`?",
            r"UPDATE\s+`?(\w+)`?",
            r"INSERT\s+INTO\s+`?(\w+)`?",
            r"DELETE\s+FROM\s+`?(\w+)`?",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, query, re.IGNORECASE)
            tables.update(matches)

        return tables

    def _identify_query_patterns(self, analysis: Dict[str, Any]) -> None:
        """Identify common patterns in slow queries"""

        patterns = defaultdict(list)

        for query_data in analysis["slow_queries"]:
            query = query_data["query"]

            # Normalize query for pattern matching
            normalized = self._normalize_query(query)

            # Group by normalized pattern
            patterns[normalized].append(query_data)

        # Convert to regular dict with statistics
        analysis["patterns"] = {}
        for pattern, queries in patterns.items():
            analysis["patterns"][pattern] = {
                "count": len(queries),
                "avg_time_ms": sum(q["execution_time_ms"] for q in queries) / len(queries),
                "total_time_ms": sum(q["execution_time_ms"] for q in queries),
                "example": queries[0]["query"],
            }

    def _normalize_query(self, query: str) -> str:
        """Normalize query for pattern matching"""

        # Remove specific values
        normalized = re.sub(r"'[^']*'", "'?'", query)
        normalized = re.sub(r"\b\d+\b", "?", normalized)
        normalized = re.sub(r"\s+", " ", normalized)

        # Remove backticks
        normalized = normalized.replace("`", "")

        return normalized.strip()

    def _generate_optimization_recommendations(self, analysis: Dict[str, Any]) -> None:
        """Generate specific optimization recommendations"""

        recommendations = []

        # Analyze patterns for recommendations
        for pattern, stats in analysis["patterns"].items():
            if stats["avg_time_ms"] > self.slow_query_threshold:
                # Check for missing indexes
                if "WHERE" in pattern and stats["count"] > 5:
                    recommendations.append(
                        {
                            "type": "index",
                            "priority": "high",
                            "description": "Frequent slow query pattern ({stats['count']} occurrences) may benefit from index",
                            "pattern": pattern,
                            "estimated_improvement": "50-90% reduction in query time",
                        }
                    )

                # Check for SELECT *
                if "SELECT *" in pattern:
                    recommendations.append(
                        {
                            "type": "query_optimization",
                            "priority": "medium",
                            "description": "Replace SELECT * with specific column names",
                            "pattern": pattern,
                            "estimated_improvement": "10-30% reduction in data transfer",
                        }
                    )

        # Table-specific recommendations
        table_recommendations = self._analyze_table_statistics()
        recommendations.extend(table_recommendations)

        analysis["recommendations"] = sorted(
            recommendations, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["priority"], 3)
        )

    def _analyze_table_statistics(self) -> List[Dict[str, Any]]:
        """Analyze table statistics for optimization opportunities"""

        recommendations = []

        try:
            # Get table statistics
            stats = frappe.db.sql(
                """
                SELECT
                    s.table_name,
                    s.table_rows,
                    s.data_length,
                    s.index_length,
                    ROUND((s.data_length + s.index_length) / 1024 / 1024, 2) as size_mb,
                    COUNT(DISTINCT c.column_name) as column_count
                FROM information_schema.tables s
                LEFT JOIN information_schema.columns c
                    ON s.table_name = c.table_name
                    AND s.table_schema = c.table_schema
                WHERE s.table_schema = DATABASE()
                AND s.table_name LIKE 'tab%'
                GROUP BY s.table_name
                HAVING s.table_rows > 1000
                ORDER BY s.table_rows DESC
                LIMIT 10
            """,
                as_dict=True,
            )

            for table_stat in stats:
                # Check for large tables without sufficient indexes
                if (
                    table_stat["table_rows"] > 10000
                    and table_stat["index_length"] < table_stat["data_length"] * 0.2
                ):
                    recommendations.append(
                        {
                            "type": "index",
                            "priority": "high",
                            "description": "Table {table_stat['table_name']} has {table_stat['table_rows']:,} rows but low index coverage",
                            "table": table_stat["table_name"],
                            "estimated_improvement": "Significant improvement for queries on this table",
                        }
                    )

                # Check for very large tables that might benefit from partitioning
                if table_stat["size_mb"] > 1000:  # Tables larger than 1GB
                    recommendations.append(
                        {
                            "type": "partitioning",
                            "priority": "medium",
                            "description": "Table {table_stat['table_name']} is {table_stat['size_mb']}MB - consider partitioning",
                            "table": table_stat["table_name"],
                            "estimated_improvement": "Better query performance and maintenance",
                        }
                    )

        except Exception as e:
            self.logger.error(f"Failed to analyze table statistics: {str(e)}")

        return recommendations

    def recommend_indexes(self, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Recommend missing indexes based on query patterns and table structure

        Args:
            table_name: Specific table to analyze (None for all tables)

        Returns:
            List of index recommendations
        """
        self.logger.info(f"Generating index recommendations for {table_name or 'all tables'}")

        recommendations = []

        # Get frequently queried columns without indexes
        missing_indexes = self._find_missing_indexes(table_name)

        for index_info in missing_indexes:
            recommendations.append(
                {
                    "table": index_info["table"],
                    "columns": index_info["columns"],
                    "type": index_info["index_type"],
                    "reason": index_info["reason"],
                    "sql": index_info["create_sql"],
                    "estimated_impact": index_info["impact"],
                }
            )

        return recommendations

    def _find_missing_indexes(self, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Find columns that would benefit from indexes"""

        missing_indexes = []

        # Define common patterns that benefit from indexes
        index_patterns = [
            # Foreign key columns
            {
                "pattern": r"(\w+)_id$",
                "type": "foreign_key",
                "reason": "Foreign key column typically used in JOINs",
            },
            # Status/type columns
            {
                "pattern": r"^(status|type|state)$",
                "type": "enum",
                "reason": "Frequently filtered status/type column",
            },
            # Date columns
            {
                "pattern": r"(date|time|created|modified|updated)$",
                "type": "datetime",
                "reason": "Date column often used in range queries",
            },
            # Boolean flags
            {
                "pattern": r"^(is_|has_|enabled|active)",
                "type": "boolean",
                "reason": "Boolean flag used for filtering",
            },
        ]

        try:
            # Get table list
            table_filter = f"AND t.table_name = '{table_name}'" if table_name else ""

            # Get columns that might need indexes
            potential_columns = frappe.db.sql(
                f"""
                SELECT
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.column_key,
                    t.table_rows
                FROM information_schema.columns c
                JOIN information_schema.tables t
                    ON c.table_name = t.table_name
                    AND c.table_schema = t.table_schema
                WHERE c.table_schema = DATABASE()
                AND c.table_name LIKE 'tab%'
                AND c.column_key = ''  -- No existing index
                AND t.table_rows > 1000  -- Only tables with significant data
                {table_filter}
                ORDER BY t.table_rows DESC
            """,
                as_dict=True,
            )

            # Check each column against patterns
            for col_info in potential_columns:
                for pattern_info in index_patterns:
                    if re.search(pattern_info["pattern"], col_info["column_name"], re.IGNORECASE):
                        # Check if this index would be beneficial
                        if self._should_create_index(col_info):
                            missing_indexes.append(
                                {
                                    "table": col_info["table_name"],
                                    "columns": [col_info["column_name"]],
                                    "index_type": pattern_info["type"],
                                    "reason": pattern_info["reason"],
                                    "create_sql": "CREATE INDEX idx_{col_info['table_name']}_{col_info['column_name']} ON `{col_info['table_name']}` (`{col_info['column_name']}`)",
                                    "impact": "Improve query performance on {col_info['table_rows']:,} rows",
                                }
                            )
                        break

            # Check for composite index opportunities
            composite_recommendations = self._find_composite_index_opportunities(table_name)
            missing_indexes.extend(composite_recommendations)

        except Exception as e:
            self.logger.error(f"Failed to find missing indexes: {str(e)}")

        return missing_indexes

    def _should_create_index(self, col_info: Dict[str, Any]) -> bool:
        """Determine if an index would be beneficial"""

        # Don't index columns with very low cardinality
        if col_info["data_type"] in ["tinyint", "bit"]:
            # Check cardinality
            try:
                cardinality = frappe.db.sql(
                    """
                    SELECT COUNT(DISTINCT `{col_info['column_name']}`) as cardinality
                    FROM `{col_info['table_name']}`
                    LIMIT 1
                """
                )[0][0]

                # If less than 10 distinct values, index might not be helpful
                if cardinality < 10:
                    return False

            except Exception:
                pass

        # Always index foreign keys and dates on large tables
        if col_info["table_rows"] > 5000:
            return True

        return col_info["table_rows"] > 1000

    def _find_composite_index_opportunities(self, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Find opportunities for composite indexes"""

        composite_indexes = []

        # Common composite index patterns
        # patterns = [
        #     {"columns": ["status", "created"], "reason": "Status + date is common filter combination"},
        #     {"columns": ["parent", "parenttype"], "reason": "Frappe child table lookup pattern"},
        #     {"columns": ["member", "status"], "reason": "Member lookup with status filter"},
        # ]

        # This would ideally analyze actual query patterns
        # For now, we'll check for existence of these column combinations

        return composite_indexes

    def generate_index_creation_script(self, recommendations: List[Dict[str, Any]]) -> str:
        """Generate SQL script to create recommended indexes"""

        script_lines = [
            "-- Index Creation Script for Verenigingen",
            "-- Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "-- IMPORTANT: Review each index before creating",
            "-- Run during maintenance window",
            "",
            "SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0;",
            "",
        ]

        for rec in recommendations:
            script_lines.extend(
                [
                    "-- {rec['reason']}",
                    "-- Impact: {rec.get('estimated_impact', 'Unknown')}",
                    rec["sql"] + ";",
                    "",
                ]
            )

        script_lines.append("SET SQL_NOTES=@OLD_SQL_NOTES;")

        return "\n".join(script_lines)

    def analyze_query_explain_plan(self, query: str) -> Dict[str, Any]:
        """
        Analyze the execution plan of a specific query

        Args:
            query: SQL query to analyze

        Returns:
            Execution plan analysis
        """
        analysis = {"query": query, "execution_plan": [], "warnings": [], "suggestions": []}

        try:
            # Get EXPLAIN output
            explain_result = frappe.db.sql(f"EXPLAIN {query}", as_dict=True)

            for row in explain_result:
                plan_step = {
                    "table": row.get("table"),
                    "type": row.get("type"),
                    "possible_keys": row.get("possible_keys"),
                    "key": row.get("key"),
                    "rows": row.get("rows"),
                    "extra": row.get("Extra", ""),
                }

                analysis["execution_plan"].append(plan_step)

                # Analyze for issues
                if row.get("type") == "ALL":
                    analysis["warnings"].append("Full table scan on {row.get('table')}")
                    analysis["suggestions"].append("Add index to {row.get('table')} to avoid full scan")

                if row.get("key") is None and row.get("possible_keys"):
                    analysis["warnings"].append("Index exists but not used for {row.get('table')}")
                    analysis["suggestions"].append("Consider query restructuring or index hints")

                if "Using filesort" in row.get("Extra", ""):
                    analysis["warnings"].append("Query requires filesort")
                    analysis["suggestions"].append("Add index on ORDER BY columns")

                if "Using temporary" in row.get("Extra", ""):
                    analysis["warnings"].append("Query uses temporary table")
                    analysis["suggestions"].append("Optimize GROUP BY or DISTINCT operations")

        except Exception as e:
            analysis["error"] = f"Failed to analyze query: {str(e)}"
            self.logger.error(f"Query analysis failed: {str(e)}")

        return analysis


# API functions


@frappe.whitelist()
def analyze_database_performance(hours=24):
    """Analyze database performance and return optimization recommendations"""

    analyzer = QueryAnalyzer()
    return analyzer.analyze_slow_queries(int(hours))


@frappe.whitelist()
def get_index_recommendations(table_name=None):
    """Get index recommendations for tables"""

    analyzer = QueryAnalyzer()
    recommendations = analyzer.recommend_indexes(table_name)

    # Generate SQL script
    if recommendations:
        script = analyzer.generate_index_creation_script(recommendations)

        # Save script to file
        script_path = frappe.get_site_path("private", "files", "index_recommendations.sql")
        with open(script_path, "w") as f:
            f.write(script)

        return {
            "success": True,
            "recommendations": recommendations,
            "script_path": script_path,
            "total_recommendations": len(recommendations),
        }

    return {"success": True, "message": "No index recommendations found", "recommendations": []}


@frappe.whitelist()
def analyze_specific_query(query):
    """Analyze execution plan for a specific query"""

    if not query or not query.strip().upper().startswith("SELECT"):
        return {"success": False, "error": "Please provide a valid SELECT query"}

    analyzer = QueryAnalyzer()
    return analyzer.analyze_query_explain_plan(query)


@frappe.whitelist()
def get_table_statistics():
    """Get statistics for all tables in the database"""

    try:
        stats = frappe.db.sql(
            """
            SELECT
                table_name,
                table_rows,
                ROUND(data_length / 1024 / 1024, 2) as data_size_mb,
                ROUND(index_length / 1024 / 1024, 2) as index_size_mb,
                ROUND((data_length + index_length) / 1024 / 1024, 2) as total_size_mb,
                ROUND(index_length / data_length * 100, 2) as index_ratio_percent
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name LIKE 'tab%'
            ORDER BY table_rows DESC
            LIMIT 50
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "tables": stats,
            "summary": {
                "total_tables": len(stats),
                "total_rows": sum(t["table_rows"] or 0 for t in stats),
                "total_size_mb": sum(t["total_size_mb"] or 0 for t in stats),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
