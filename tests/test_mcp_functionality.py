#!/usr/bin/env python3
"""
Test MCP tool functionality to identify working and problematic tools.
This script systematically tests various MCP tools to identify issues.
"""

import os
import sys
import time
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def test_tool_with_timeout(tool_func, *args, timeout=30, **kwargs):
    """Test a tool with timeout to detect hanging tools."""
    print(f"🔍 Testing tool with timeout {timeout}s...")
    start_time = time.time()

    try:
        # Use a simple approach - just call the function
        result = tool_func(*args, **kwargs)
        elapsed = time.time() - start_time

        if elapsed > timeout:
            print(f"⚠️  TIMEOUT: Tool took {elapsed:.1f}s (limit: {timeout}s)")
            return {"status": "timeout", "result": None, "time": elapsed}
        elif result is None:
            print(f"❌ FAILED: Tool returned None")
            return {"status": "failed", "result": None, "time": elapsed}
        else:
            print(f"✅ SUCCESS: Tool completed in {elapsed:.1f}s")
            return {"status": "success", "result": result, "time": elapsed}
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ ERROR: {str(e)[:100]} ({elapsed:.1f}s)")
        return {"status": "error", "result": str(e), "time": elapsed}

def test_basic_tools():
    """Test basic file and search tools."""
    print("\n" + "="*60)
    print("🔧 TESTING BASIC TOOLS")
    print("="*60)

    results = {}

    # Test read_file
    try:
        from tools import read_file
        result = test_tool_with_timeout(read_file, "MSCodeBase/AGENT_DIARY.md", timeout=10)
        results["read_file"] = result
    except Exception as e:
        print(f"❌ read_file import failed: {e}")
        results["read_file"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test grep
    try:
        from tools import grep
        result = test_tool_with_timeout(grep, "def get_stale_files", "MSCodeBase/src/core/index_guard.py", timeout=10)
        results["grep"] = result
    except Exception as e:
        print(f"❌ grep import failed: {e}")
        results["grep"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test find_path
    try:
        from tools import find_path
        result = test_tool_with_timeout(find_path, "*.py", "MSCodeBase/src", timeout=10)
        results["find_path"] = result
    except Exception as e:
        print(f"❌ find_path import failed: {e}")
        results["find_path"] = {"status": "import_error", "result": str(e), "time": 0}

    return results

def test_index_tools():
    """Test indexing tools."""
    print("\n" + "="*60)
    print("📊 TESTING INDEX TOOLS")
    print("="*60)

    results = {}

    # Test get_index_status
    try:
        from tools import get_index_status
        result = test_tool_with_timeout(get_index_status, timeout=10)
        results["get_index_status"] = result
    except Exception as e:
        print(f"❌ get_index_status import failed: {e}")
        results["get_index_status"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_index_progress
    try:
        from tools import get_index_progress
        result = test_tool_with_timeout(get_index_progress, timeout=10)
        results["get_index_progress"] = result
    except Exception as e:
        print(f"❌ get_index_progress import failed: {e}")
        results["get_index_progress"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_index_timeline
    try:
        from tools import get_index_timeline
        result = test_tool_with_timeout(get_index_timeline, timeout=10)
        results["get_index_timeline"] = result
    except Exception as e:
        print(f"❌ get_index_timeline import failed: {e}")
        results["get_index_timeline"] = {"status": "import_error", "result": str(e), "time": 0}

    return results

def test_analysis_tools():
    """Test analysis tools."""
    print("\n" + "="*60)
    print("🔍 TESTING ANALYSIS TOOLS")
    print("="*60)

    results = {}

    # Test get_symbol_info
    try:
        from tools import get_symbol_info
        result = test_tool_with_timeout(get_symbol_info, "get_stale_files", timeout=10)
        results["get_symbol_info"] = result
    except Exception as e:
        print(f"❌ get_symbol_info import failed: {e}")
        results["get_symbol_info"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_related_files
    try:
        from tools import get_related_files
        result = test_tool_with_timeout(get_related_files, "MSCodeBase", "src/core/index_guard.py", timeout=10)
        results["get_related_files"] = result
    except Exception as e:
        print(f"❌ get_related_files import failed: {e}")
        results["get_related_files"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test impact_analysis
    try:
        from tools import impact_analysis
        result = test_tool_with_timeout(impact_analysis, "get_stale_files", timeout=10)
        results["impact_analysis"] = result
    except Exception as e:
        print(f"❌ impact_analysis import failed: {e}")
        results["impact_analysis"] = {"status": "import_error", "result": str(e), "time": 0}

    return results

def test_intel_tools():
    """Test high-level intel tools."""
    print("\n" + "="*60)
    print("🧠 TESTING INTEL TOOLS")
    print("="*60)

    results = {}

    # Test intel_get_runtime_status
    try:
        from tools import intel_get_runtime_status
        result = test_tool_with_timeout(intel_get_runtime_status, timeout=10)
        results["intel_get_runtime_status"] = result
    except Exception as e:
        print(f"❌ intel_get_runtime_status import failed: {e}")
        results["intel_get_runtime_status"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test intel_trigger_reindex
    try:
        from tools import intel_trigger_reindex
        result = test_tool_with_timeout(intel_trigger_reindex, timeout=10)
        results["intel_trigger_reindex"] = result
    except Exception as e:
        print(f"❌ intel_trigger_reindex import failed: {e}")
        results["intel_trigger_reindex"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test intel_get_job_status (we'll skip this as it needs a job_id)
    try:
        from tools import intel_get_job_status
        # This would need a valid job_id to test properly
        results["intel_get_job_status"] = {"status": "skipped", "result": "needs_job_id", "time": 0}
    except Exception as e:
        print(f"❌ intel_get_job_status import failed: {e}")
        results["intel_get_job_status"] = {"status": "import_error", "result": str(e), "time": 0}

    return results

def test_search_tools():
    """Test search tools."""
    print("\n" + "="*60)
    print("🔎 TESTING SEARCH TOOLS")
    print("="*60)

    results = {}

    # Test search_code
    try:
        from tools import search_code
        result = test_tool_with_timeout(search_code, "get_stale_files", timeout=10)
        results["search_code"] = result
    except Exception as e:
        print(f"❌ search_code import failed: {e}")
        results["search_code"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test smart_search
    try:
        from tools import smart_search
        result = test_tool_with_timeout(smart_search, "get_stale_files", mode="fast", timeout=10)
        results["smart_search"] = result
    except Exception as e:
        print(f"❌ smart_search import failed: {e}")
        results["smart_search"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test context_search
    try:
        from tools import context_search, read_file
        code = read_file("MSCodeBase/src/core/index_guard.py")
        if code:
            result = test_tool_with_timeout(context_search, selected_code=code[:500], timeout=10)
            results["context_search"] = result
        else:
            results["context_search"] = {"status": "skipped", "result": "no_code", "time": 0}
    except Exception as e:
        print(f"❌ context_search import failed: {e}")
        results["context_search"] = {"status": "import_error", "result": str(e), "time": 0}

    return results

def test_cross_project_tools():
    """Test cross-project tools."""
    print("\n" + "="*60)
    print("🌐 TESTING CROSS-PROJECT TOOLS")
    print("="*60)

    results = {}

    # Test cross_project_deps
    try:
        from tools import cross_project_deps
        result = test_tool_with_timeout(cross_project_deps, action="graph", timeout=10)
        results["cross_project_deps"] = result
    except Exception as e:
        print(f"❌ cross_project_deps import failed: {e}")
        results["cross_project_deps"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test cross_repo_search
    try:
        from tools import cross_repo_search
        result = test_tool_with_timeout(cross_repo_search, "get_stale_files", timeout=10)
        results["cross_repo_search"] = result
    except Exception as e:
        print(f"❌ cross_repo_search import failed: {e}")
        results["cross_repo_search"] = {"status": "import_error", "result": str(e), "time": 0}

    return results

def test_diagnostic_tools():
    """Test diagnostic tools."""
    print("\n" + "="*60)
    print("🩺 TESTING DIAGNOSTIC TOOLS")
    print("="*60)

    results = {}

    # Test get_health_report
    try:
        from tools import get_health_report
        result = test_tool_with_timeout(get_health_report, project_root="MSCodeBase", timeout=10)
        results["get_health_report"] = result
    except Exception as e:
        print(f"❌ get_health_report import failed: {e}")
        results["get_health_report"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_logs
    try:
        from tools import get_logs
        result = test_tool_with_timeout(get_logs, project_root="MSCodeBase", timeout=10)
        results["get_logs"] = result
    except Exception as e:
        print(f"❌ get_logs import failed: {e}")
        results["get_logs"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_bug_correlation
    try:
        from tools import get_bug_correlation
        result = test_tool_with_timeout(get_bug_correlation, project_root="MSCodeBase", timeout=10)
        results["get_bug_correlation"] = result
    except Exception as e:
        print(f"❌ get_bug_correlation import failed: {e}")
        results["get_bug_correlation"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_hotspots
    try:
        from tools import get_hotspots
        result = test_tool_with_timeout(get_hotspots, project_root="MSCodeBase", timeout=10)
        results["get_hotspots"] = result
    except Exception as e:
        print(f"❌ get_hotspots import failed: {e}")
        results["get_hotspots"] = {"status": "import_error", "result": str(e), "time": 0}

    return results

def analyze_results(all_results):
    """Analyze test results and identify issues."""
    print("\n" + "="*60)
    print("📊 ANALYSIS OF RESULTS")
    print("="*60)

    summary = {
        "total_tools": 0,
        "successful": 0,
        "failed": 0,
        "timeout": 0,
        "error": 0,
        "import_error": 0,
        "skipped": 0,
        "problematic_tools": []
    }

    for category, results in all_results.items():
        print(f"\n📋 Category: {category}")
        for tool_name, result in results.items():
            summary["total_tools"] += 1
            status = result.get("status", "unknown")

            if status == "success":
                summary["successful"] += 1
                print(f"  ✅ {tool_name}: SUCCESS ({result['time']:.1f}s)")
            elif status == "timeout":
                summary["timeout"] += 1
                summary["problematic_tools"].append(tool_name)
                print(f"  ⚠️  {tool_name}: TIMEOUT ({result['time']:.1f}s)")
            elif status == "error":
                summary["error"] += 1
                summary["problematic_tools"].append(tool_name)
                print(f"  ❌ {tool_name}: ERROR ({result['time']:.1f}s)")
            elif status == "import_error":
                summary["import_error"] += 1
                summary["problematic_tools"].append(tool_name)
                print(f"  🚫 {tool_name}: IMPORT ERROR")
            elif status == "skipped":
                summary["skipped"] += 1
                print(f"  ⏭️  {tool_name}: SKIPPED")

    print(f"\n🎯 OVERALL SUMMARY:")
    print(f"  Total tools tested: {summary['total_tools']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Timeout: {summary['timeout']}")
    print(f"  Error: {summary['error']}")
    print(f"  Import Error: {summary['import_error']}")
    print(f"  Skipped: {summary['skipped']}")

    if summary["problematic_tools"]:
        print(f"\n⚠️  PROBLEMATIC TOOLS:")
        for tool in summary["problematic_tools"]:
            print(f"  - {tool}")

    return summary

def main():
    """Run comprehensive MCP tool functionality test."""
    print("🚀 Starting MCP Tool Functionality Test")
    print("="*60)

    # Run all test categories
    all_results = {}

    all_results["basic_tools"] = test_basic_tools()
    all_results["index_tools"] = test_index_tools()
    all_results["analysis_tools"] = test_analysis_tools()
    all_results["intel_tools"] = test_intel_tools()
    all_results["search_tools"] = test_search_tools()
    all_results["cross_project_tools"] = test_cross_project_tools()
    all_results["diagnostic_tools"] = test_diagnostic_tools()

    # Analyze results
    summary = analyze_results(all_results)

    # Save results to file
    results_file = "MSCodeBase/mcp_tool_test_results.json"
    import json
    with open(results_file, 'w') as f:
        json.dump({
            "timestamp": time.time(),
            "summary": summary,
            "detailed_results": all_results
        }, f, indent=2)

    print(f"\n💾 Results saved to: {results_file}")

    # Return appropriate exit code
    if summary["timeout"] > 0 or summary["error"] > 0 or summary["import_error"] > 0:
        print(f"\n⚠️  Test completed with issues. {summary['timeout']} timeouts, {summary['error']} errors, {summary['import_error']} import errors.")
        return 1
    else:
        print(f"\n🎉 All tests passed successfully!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
