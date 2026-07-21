"""Test suppression markers for dead code detection."""
import gc
import tempfile
from pathlib import Path


def test_suppression_markers():
    """Test that suppression markers work correctly."""
    # Create temp file with suppression marker
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("""
def used_function():
    pass

# mscodebase-ignore-next-line
def unused_function():  # Should be suppressed
    pass

def another_unused():  # Should be detected
    pass
""")
        temp_path = f.name

    try:
        from src.core.graph import PropertyGraph

        # Create temp graph
        # Windows: sqlite3 WAL-файл может держать блокировку даже после close().
        # ignore_cleanup_errors=True — tempfile не падает при PermissionError.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            graph = PropertyGraph(db_path)

            # Add nodes manually for testing
            graph.add_node(
                name="used_function",
                label="Function",
                qualified_name="used_function",
                file_path=temp_path,
                properties={"start_line": 2}
            )
            # start_line=6: функция `def unused_function():` на строке 6
            # (строка 5 = `# mscodebase-ignore-next-line` → suppressed={6})
            graph.add_node(
                name="unused_function",
                label="Function",
                qualified_name="unused_function",
                file_path=temp_path,
                properties={"start_line": 6}
            )
            graph.add_node(
                name="another_unused",
                label="Function",
                qualified_name="another_unused",
                file_path=temp_path,
                properties={"start_line": 9}
            )

            # Test suppression detection
            suppressed = graph._parse_suppressions(temp_path)
            print(f"Suppressed lines: {suppressed}")

            # Line 6 should be suppressed (after # mscodebase-ignore-next-line on line 5)
            assert 6 in suppressed, f"Line 6 should be suppressed, got {suppressed}"

            # Test SARIF output
            sarif = graph.detect_dead_code_sarif()
            print(f"SARIF results: {len(sarif.get('runs', [{}])[0].get('results', []))} results")

            # Should have 1 result (another_unused), not 2
            results = sarif.get('runs', [{}])[0].get('results', [])
            # used_function (start_line=2) тоже dead (нет вызовов)
            # unused_function (start_line=6) подавлен # mscodebase-ignore-next-line → не в results
            # another_unused (start_line=9) dead
            # Итого: 2 результата (used_function + another_unused)
            assert len(results) == 2, f"Expected 2 results (used_function + another_unused), got {len(results)}"

            print("✅ Suppression markers test passed!")
            # Явно закрываем graph до выхода из TemporaryDirectory (Windows sqlite3 lock)
            graph.close()
            del graph
            gc.collect()
    finally:
        Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    test_suppression_markers()
