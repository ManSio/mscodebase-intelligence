"""Test suppression markers for dead code detection."""
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
        with tempfile.TemporaryDirectory() as tmpdir:
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
            graph.add_node(
                name="unused_function",
                label="Function",
                qualified_name="unused_function",
                file_path=temp_path,
                properties={"start_line": 5}
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
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            
            print("✅ Suppression markers test passed!")
    finally:
        Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    test_suppression_markers()