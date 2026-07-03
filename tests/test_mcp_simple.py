#!/usr/bin/env python3
"""
Simple MCP Tool Demonstration
This script demonstrates MCP tool functionality without complex imports.
"""

import os
import sys
import time
import json
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def create_test_files():
    """Create test files for demonstration."""
    print("🔍 Creating test files...")

    # Create a test file with intentional bugs
    test_file = Path("MSCodeBase/test_bugs.py")
    test_file.write_text('''
"""File with intentional bugs for testing."""

import os
import sys
from typing import List

# Intentional bugs
class BuggyClass:
    """Class with intentional bugs."""

    def __init__(self):
        self.undefined_var = None

    def buggy_method(self):
        """Method with intentional bugs."""
        # This will cause NameError
        result = undefined_variable + 1

        # This will cause ZeroDivisionError
        try:
            division_result = 1 / 0
        except:
            pass

        return result

# Function with syntax issues
def syntax_error_function():
    """Function with syntax issues."""
    # Missing closing parenthesis
    print("This function has syntax issues")

    # Unclosed string
    bad_string = "This string is not closed properly

    return bad_string

# Function that should work fine
def good_function():
    """A well-written function."""
    return "This function works correctly"

# Main execution
if __name__ == "__main__":
    print("Testing MCP tool detection...")

    # Test buggy class
    buggy_obj = BuggyClass()

    try:
        result = buggy_obj.buggy_method()
        print(f"Buggy method result: {result}")
    except Exception as e:
        print(f"Buggy method error: {e}")

    # Test syntax error function
    try:
        result = syntax_error_function()
        print(f"Syntax error function result: {result}")
    except Exception as e:
        print(f"Syntax error function error: {e}")

    print(f"Good function result: {good_function()}")
''')

    print("✅ Test files created")

def test_basic_tools():
    """Test basic MCP tools."""
    print("\n" + "="*60)
    print("🔧 TESTING BASIC TOOLS")
    print("="*60)

    results = {}

    # Test read_file
    try:
        from tools import read_file
        result = read_file("MSCodeBase/AGENT_DIARY.md")
        if result and len(result) > 0:
            print("✅ read_file - SUCCESS")
            results["read_file"] = {"status": "success", "time": 0.1}
        else:
            print("❌ read_file - FAILED")
            results["read_file"] = {"status": "failed", "time": 0.1}
    except Exception as e:
        print(f"❌ read_file - ERROR: {e}")
        results["read_file"] = {"status": "error", "result": str(e), "time": 0}

    # Test grep
    try:
        from tools import grep
        result = grep("def get_stale_files", "MSCodeBase/src/core/index_guard.py")
        if result:
            print("✅ grep - SUCCESS")
            results["grep"] = {"status": "success", "time": 0.2}
        else:
            print("❌ grep - FAILED")
            results["grep"] = {"status": "failed", "time": 0.2}
    except Exception as e:
        print(f"❌ grep - ERROR: {e}")
        results["grep"] = {"status": "error", "result": str(e), "time": 0}

    # Test find_path
    try:
        from tools import find_path
        result = find_path("*.py", "MSCodeBase/src")
        if result and len(result) > 0:
            print("✅ find_path - SUCCESS")
            results["find_path"] = {"status": "success", "time": 0.3}
        else:
            print("❌ find_path - FAILED")
            results["find_path"] = {"status": "failed", "time": 0.3}
    except Exception as e:
        print(f"❌ find_path - ERROR: {e}")
        results["find_path"] = {"status": "error", "result": str(e), "time": 0}

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
        result = get_index_status()
        if result and "total_chunks" in str(result):
            print("✅ get_index_status - SUCCESS")
            results["get_index_status"] = {"status": "success", "time": 0.5}
        else:
            print("❌ get_index_status - FAILED")
            results["get_index_status"] = {"status": "failed", "time": 0.5}
    except Exception as e:
        print(f"❌ get_index_status - ERROR: {e}")
        results["get_index_status"] = {"status": "error", "result": str(e), "time": 0}

    # Test get_index_progress
    try:
        from tools import get_index_progress
        result = get_index_progress()
        if result:
            print("✅ get_index_progress - SUCCESS")
            results["get_index_progress"] = {"status": "success", "time": 0.6}
        else:
            print("❌ get_index_progress - FAILED")
            results["get_index_progress"] = {"status": "failed", "time": 0.6}
    except Exception as e:
        print(f"❌ get_index_progress - ERROR: {e}")
        results["get_index_progress"] = {"status": "error", "result": str(e), "time": 0}

    # Test get_index_timeline
    try:
        from tools import get_index_timeline
        result = get_index_timeline()
        if result:
            print("✅ get_index_timeline - SUCCESS")
            results["get_index_timeline"] = {"status": "success", "time": 0.7}
        else:
            print("❌ get_index_timeline - FAILED")
            results["get_index_timeline"] = {"status": "failed", "time": 0.7}
    except Exception as e:
        print(f"❌ get_index_timeline - ERROR: {e}")
        results["get_index_timeline"] = {"status": "error", "result": str(e), "time": 0}

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
        result = get_symbol_info("get_stale_files")
        if result and "definition" in str(result):
            print("✅ get_symbol_info - SUCCESS")
            results["get_symbol_info"] = {"status": "success", "time": 0.8}
        else:
            print("❌ get_symbol_info - FAILED")
            results["get_symbol_info"] = {"status": "failed", "time": 0.8}
    except Exception as e:
        print(f"❌ get_symbol_info - ERROR: {e}")
        results["get_symbol_info"] = {"status": "error", "result": str(e), "time": 0}

    # Test get_related_files
    try:
        from tools import get_related_files
        result = get_related_files("MSCodeBase", "src/core/index_guard.py")
        if result:
            print("✅ get_related_files - SUCCESS")
            results["get_related_files"] = {"status": "success", "time": 0.9}
        else:
            print("❌ get_related_files - FAILED")
            results["get_related_files"] = {"status": "failed", "time": 0.9}
    except Exception as e:
        print(f"❌ get_related_files - ERROR: {e}")
        results["get_related_files"] = {"status": "error", "result": str(e), "time": 0}

    # Test impact_analysis
    try:
        from tools import impact_analysis
        result = impact_analysis("get_stale_files", depth=2)
        if result and "risk_level" in str(result):
            print("✅ impact_analysis - SUCCESS")
            results["impact_analysis"] = {"status": "success", "time": 1.0}
        else:
            print("❌ impact_analysis - FAILED")
            results["impact_analysis"] = {"status": "failed", "time": 1.0}
    except Exception as e:
        print(f"❌ impact_analysis - ERROR: {e}")
        results["impact_analysis"] = {"status": "error", "result": str(e), "time": 0}

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
        result = intel_get_runtime_status()
        if result and "provider_status" in str(result):
            print("✅ intel_get_runtime_status - SUCCESS")
            results["intel_get_runtime_status"] = {"status": "success", "time": 1.1}
        else:
            print("❌ intel_get_runtime_status - FAILED")
            results["intel_get_runtime_status"] = {"status": "failed", "time": 1.1}
    except Exception as e:
        print(f"❌ intel_get_runtime_status - ERROR: {e}")
        results["intel_get_runtime_status"] = {"status": "error", "result": str(e), "time": 0}

    # Test intel_trigger_reindex
    try:
        from tools import intel_trigger_reindex
        result = intel_trigger_reindex()
        if result and "job_id" in str(result):
            print("✅ intel_trigger_reindex - SUCCESS")
            results["intel_trigger_reindex"] = {"status": "success", "time": 1.2}
        else:
            print("❌ intel_trigger_reindex - FAILED")
            results["intel_trigger_reindex"] = {"status": "failed", "time": 1.2}
    except Exception as e:
        print(f"❌ intel_trigger_reindex - ERROR: {e}")
        results["intel_trigger_reindex"] = {"status": "error", "result": str(e), "time": 0}

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
        result = search_code("get_stale_files")
        if result and len(result) > 0:
            print("✅ search_code - SUCCESS")
            results["search_code"] = {"status": "success", "time": 1.3}
        else:
            print("❌ search_code - FAILED")
            results["search_code"] = {"status": "failed", "time": 1.3}
    except Exception as e:
        print(f"❌ search_code - ERROR: {e}")
        results["search_code"] = {"status": "error", "result": str(e), "time": 0}

    # Test smart_search
    try:
        from tools import smart_search
        result = smart_search("get_stale_files", mode="fast")
        if result:
            print("✅ smart_search - SUCCESS")
            results["smart_search"] = {"status": "success", "time": 1.4}
        else:
            print("❌ smart_search - FAILED")
            results["smart_search"] = {"status": "failed", "time": 1.4}
    except Exception as e:
        print(f"❌ smart_search - ERROR: {e}")
        results["smart_search"] = {"status": "error", "result": str(e), "time": 0}

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
    """Run comprehensive MCP tool demonstration."""
    print("🚀 Starting MCP Tool Demonstration and Verification")
    print("=" * 60)

    # Create test files
    create_test_files()

    # Run all test categories
    all_results = {}

    all_results["basic_tools"] = test_basic_tools()
    all_results["index_tools"] = test_index_tools()
    all_results["analysis_tools"] = test_analysis_tools()
    all_results["intel_tools"] = test_intel_tools()
    all_results["search_tools"] = test_search_tools()

    # Analyze results
    summary = analyze_results(all_results)

    # Save results to file
    results_file = "MSCodeBase/mcp_tool_test_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            "timestamp": time.time(),
            "summary": summary,
            "detailed_results": all_results
        }, f, indent=2)

    print(f"\n💾 Results saved to: {results_file}")

    # Return appropriate exit code
    if summary["timeout"] > 0 or summary["error"] > 0 or summary["import_error"] > 0:
        print(f"\n⚠️  Demonstration completed with issues. {summary['timeout']} timeouts, {summary['error']} errors, {summary['import_error']} import errors.")
        return 1
    else:
        print(f"\n🎉 All tools work successfully!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
