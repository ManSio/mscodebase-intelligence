"""
MCP Tools Module
This module provides all MCP tools for testing and demonstration.
All tools are imported from the MCP server implementation.
"""

import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import all MCP tools from the server module
from mcp.server import (
    # Basic tools
    read_file,
    grep,
    find_path,

    # Index tools
    get_index_status,
    get_index_progress,
    get_index_timeline,

    # Analysis tools
    get_symbol_info,
    get_related_files,
    impact_analysis,

    # Intel tools
    intel_get_runtime_status,
    intel_trigger_reindex,
    intel_get_job_status,

    # Search tools
    search_code,
    smart_search,
    context_search,

    # Cross-project tools
    cross_project_deps,
    cross_repo_search,

    # Diagnostic tools
    get_health_report,
    get_logs,
    get_bug_correlation,
    get_hotspots,

    # Additional tools that might be needed
    intel_get_hotspots,
    intel_get_project_memory,
    intel_predict_root_cause,
    intel_log_incident,
    intel_find_similar_incidents,
    intel_add_memory_node,
    intel_get_code_hotspots,
)

# Create a clean namespace for all tools
__all__ = [
    'read_file', 'grep', 'find_path',
    'get_index_status', 'get_index_progress', 'get_index_timeline',
    'get_symbol_info', 'get_related_files', 'impact_analysis',
    'intel_get_runtime_status', 'intel_trigger_reindex', 'intel_get_job_status',
    'search_code', 'smart_search', 'context_search',
    'cross_project_deps', 'cross_repo_search',
    'get_health_report', 'get_logs', 'get_bug_correlation', 'get_hotspots',
    'intel_get_hotspots', 'intel_get_project_memory', 'intel_predict_root_cause',
    'intel_log_incident', 'intel_find_similar_incidents', 'intel_add_memory_node',
    'intel_get_code_hotspots',
]
