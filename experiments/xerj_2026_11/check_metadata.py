"""P0-5 acceptance, as a command: public metadata must agree with FACTS.md."""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

root = pathlib.Path(__file__).resolve().parents[2]
text = (root / "pyproject.toml").read_text(encoding="utf-8")

checks = []
checks.append(("no 'analysis tools' claim", "analysis tools" not in text.lower()))
# mojibake: UTF-8 read as cp1251 leaves characters from the Latin-1 range in a
# Russian sentence, or the tell-tale "вЂ"/"РІР" pairs. § and ° are legitimate.
ALLOWED_LATIN1 = {"§", "°", "×"}
suspicious = {ch for ch in text if "\u0080" <= ch <= "\u00ff"} - ALLOWED_LATIN1
pairs = [p for p in ("вЂ", "РІР", "СЃ", "в„") if p in text]
mojibake = sorted(suspicious) + pairs
checks.append(("no mojibake", not mojibake))
checked = re.search(r"requires-python\s*=\s*\"([^\"]+)\"", text)
checks.append(("requires-python >=3.14", bool(checked) and checked.group(1) == ">=3.14"))
classifiers = re.findall(r'"Programming Language :: Python :: ([0-9.]+)"', text)
checks.append(("classifiers match 3.14 only", classifiers == ["3.14"]))
counts = re.findall(r"\b(\d+)\b", text)
declared = re.search(r"(\d+) MCP tools behind", text)
checks.append(("tool count named once, as 69", bool(declared) and declared.group(1) == "69"))

facts = (root / "docs" / "FACTS.md").read_text(encoding="utf-8")
facts_69 = re.search(r"Registered tools \| \*\*(\d+)\*\*", facts)
checks.append(("FACTS agrees on 69", bool(facts_69) and facts_69.group(1) == "69"))

ok = True
for name, passed in checks:
    print(f"{'PASS' if passed else 'FAIL'}  {name}")
    ok &= passed
print(f"\nclassifiers={classifiers} requires-python={checked.group(1) if checked else '?'} "
      f"mojibake_hits={len(mojibake)}")
sys.exit(0 if ok else 1)
