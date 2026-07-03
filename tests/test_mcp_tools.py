#!/usr/bin/env python3
"""
Test script to verify MCP tools functionality.
This script tests various MCP tools to identify working ones and problematic ones.
"""

import os
import sys
import time
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def test_basic_file_operations():
    """Test basic file operations."""
    print("=== Testing Basic File Operations ===")

    # Test 1: Read existing file
    try:
        from tools import read_file
        result = read_file("MSCodeBase/AGENT_DIARY.md")
        print("✓ read_file works")
        return True
    except Exception as e:
        print(f"✗ read_file failed: {e}")
        return False

def test_search_tools():
    """Test search-related tools."""
    print("\n=== Testing Search Tools ===")

    # Test grep
    try:
        from tools import grep
        result = grep("def get_stale_files", "MSCodeBase/src/core/index_guard.py")
        print("✓ grep works")
        return True
    except Exception as e:
        print(f"✗ grep failed: {e}")
        return False

def test_index_tools():
    """Test indexing tools."""
    print("\n=== Testing Index Tools ===")

    # Test index status
    try:
        from tools import get_index_status
        result = get_index_status()
        print("✓ get_index_status works")
        return True
    except Exception as e:
        print(f"✗ get_index_status failed: {e}")
        return False

def test_analysis_tools():
    """Test analysis tools."""
    print("\n=== Testing Analysis Tools ===")

    # Test symbol info
    try:
        from tools import get_symbol_info
        result = get_symbol_info("get_stale_files")
        print("✓ get_symbol_info works")
        return True
    except Exception as e:
        print(f"✗ get_symbol_info failed: {e}")
        return False

def test_intel_tools():
    """Test high-level intel tools."""
    print("\n=== Testing Intel Tools ===")

    # Test runtime status
    try:
        from tools import intel_get_runtime_status
        result = intel_get_runtime_status()
        print("✓ intel_get_runtime_status works")
        return True
    except Exception as e:
        print(f"✗ intel_get_runtime_status failed: {e}")
        return False

def main():
    """Run all tests."""
    print("Starting MCP Tools Test Suite")
    print("=" * 50)

    tests = [
        test_basic_file_operations,
        test_search_tools,
        test_index_tools,
        test_analysis_tools,
        test_intel_tools,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            results.append(False)

    print("\n" + "=" * 50)
    print("Test Summary:")
    print(f"Passed: {sum(results)}/{len(results)}")
    print(f"Failed: {len(results) - sum(results)}/{len(results)}")

    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
