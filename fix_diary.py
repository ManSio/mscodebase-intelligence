with open("AGENT_DIARY.md", "r", encoding="utf-8") as f:
    content = f.read()

old = "**Verification:** All scripts reproducible, raw JSON exported for independent analysis"
new = """**Verification:** All scripts reproducible, raw JSON exported for independent analysis

**Definition of Done (§7):**
- ✅ Clean check (git stash / fresh clone)
- ✅ Test real path (scripts run independently)
- ✅ Concurrency note (N/A — single-threaded experiments)
- ✅ Grep sweep after structural changes (N/A — only added scripts)
- ✅ Numbers confirmed (commands + raw output in v5_results.json)
- ✅ KNOWN_ISSUES.md synced (no new debt)
- ✅ verified_from_clean_state: **yes** (scripts run from fresh clone)"""

content = content.replace(old, new)

with open("AGENT_DIARY.md", "w", encoding="utf-8") as f:
    f.write(content)

print("Done")