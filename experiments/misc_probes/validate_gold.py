#!/usr/bin/env python3
"""Validate GOLD standard paths against actual repo structure."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gold_standard import GOLD

PROJECT = Path(r"D:\Project\MSCodeBase")
SRC = PROJECT / "src"

def scan_files():
    """Scan all Python files in entire project."""
    files = {}
    for py in sorted(PROJECT.rglob("*.py")):
        if "__pycache__" in str(py) or ".git" in str(py):
            continue
        rel = str(py.relative_to(PROJECT)).replace("\\", "/")
        files[rel] = True
    return files

def main():
    print("=" * 70)
    print("GOLD STANDARD VALIDATION")
    print("=" * 70)
    
    all_files = scan_files()
    print(f"Total files in src/: {len(all_files)}")
    
    missing = []
    present = []
    ambiguous = []
    
    for query, gold_path in GOLD.items():
        # Normalize path
        gold_path = gold_path.replace("\\", "/")
        
        # Check if exact match
        if gold_path in all_files:
            present.append((query, gold_path))
        else:
            # Check if it's a directory
            if any(f.startswith(gold_path.rstrip("/") + "/") for f in all_files):
                ambiguous.append((query, gold_path, "is_dir"))
            elif gold_path.endswith(".py") and gold_path in all_files:
                # This shouldn't happen but just in case
                present.append((query, gold_path))
            else:
                missing.append((query, gold_path))
    
    print(f"\n{'='*70}")
    print(f"PRESENT: {len(present)}")
    print(f"MISSING: {len(missing)}")
    print(f"AMBIGUOUS (is dir): {len(ambiguous)}")
    
    if missing:
        print(f"\n{'='*70}")
        print("MISSING PATHS:")
        for query, path in missing:
            print(f"  '{query}' -> '{path}'")
    
    if ambiguous:
        print(f"\n{'='*70}")
        print("AMBIGUOUS (path is directory):")
        for query, path, reason in ambiguous:
            print(f"  '{query}' -> '{path}' ({reason})")
    
    print(f"\n{'='*70}")
    print("SUMMARY:")
    print(f"  Valid gold paths: {len(present)} / {len(GOLD)} ({len(present)/len(GOLD)*100:.0f}%)")
    print(f"  Invalid gold paths: {len(missing)} / {len(GOLD)} ({len(missing)/len(GOLD)*100:.0f}%)")
    print(f"  Ambiguous (dir): {len(ambiguous)}")
    
    # Save results
    import json
    result = {
        "total_queries": len(GOLD),
        "present": len(present),
        "missing": len(missing),
        "ambiguous": len(ambiguous),
        "missing_queries": [q for q, _ in missing],
        "valid_rate": len(present) / len(GOLD) * 100
    }
    with open("experiments/gold_validation.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved to experiments/gold_validation.json")

if __name__ == "__main__":
    main()