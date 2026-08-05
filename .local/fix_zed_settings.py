"""Surgical edit of Zed settings.json — 3 changes (crash-loop mitigation).

Changes:
1. edit_predictions object -> false          (403 каждый старт, лишняя нагрузка)
2. agent.auto_compact.enabled: false -> true (сессии перестанут расти до ГБ)
3. context_servers_to_query: 2 -> 1          (firefox-browser-control убран)
"""
import io
import json
import sys

try:
    p = r"C:\Users\misha\AppData\Roaming\Zed\settings.json"
    raw = io.open(p, encoding="utf-8").read()
    nl = "\r\n" if "\r\n" in raw else "\n"

    def block(lines):
        return nl.join(lines) + nl

    s = raw

    # 1. edit_predictions {open_ai_compatible_api...} -> false
    old_ep = block([
        '    "edit_predictions": {',
        '        "open_ai_compatible_api": {',
        '            "prompt_format": "infer"',
        "        }",
        "    },",
    ])
    assert old_ep in s, "edit_predictions block NOT found"
    s = s.replace(old_ep, '    "edit_predictions": false,' + nl)

    # 2. auto_compact: enabled true + threshold 65
    old_ac = block([
        '        "auto_compact": {',
        '            "enabled": false,',
        '            "threshold": 85',
        "        },",
    ])
    new_ac = block([
        '        "auto_compact": {',
        '            "enabled": true,',
        '            "threshold": 65',
        "        },",
    ])
    assert old_ac in s, "auto_compact block NOT found"
    s = s.replace(old_ac, new_ac)

    # 3. context_servers_to_query: remove firefox-browser-control
    old_cs = '"context_servers_to_query": ["mscodebase-intelligence", "firefox-browser-control"]'
    new_cs = '"context_servers_to_query": ["mscodebase-intelligence"]'
    assert old_cs in s, "context_servers_to_query NOT found"
    s = s.replace(old_cs, new_cs)

    # Validate before writing
    json.loads(s)  # raises on invalid JSON
    io.open(p, "w", encoding="utf-8", newline="").write(s)
    print("OK: 3 changes applied, JSON valid")
except Exception:
    import traceback

    traceback.print_exc()
    sys.exit(1)
