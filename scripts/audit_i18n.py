#!/usr/bin/env python3
"""Audit: find user-facing strings NOT wrapped in _()"""

import ast
import os
import re
import sys

src_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
)
unwrapped = []

for root, dirs, files in os.walk(src_dir):
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()

        # Find return statements with string literals containing emoji or Russian
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            # Skip comments, docstrings, empty lines
            if (
                not stripped
                or stripped.startswith("#")
                or stripped.startswith('"""')
                or stripped.startswith("'''")
            ):
                continue
            # Check if line has return with string containing emoji
            if 'return "' in stripped or "return '" in stripped:
                # Check if it's already wrapped in _()
                if not stripped.replace("return ", "").strip().startswith("_("):
                    # Check if it contains emoji or Russian chars
                    has_emoji = bool(
                        re.search(
                            r"[📦🔍✅❌📊📋🌐🟢🔴⏱🔬📄📎ℹ️💡🔥🧠\u0400-\u04ff]", stripped
                        )
                    )
                    if has_emoji:
                        rel = os.path.relpath(
                            path,
                            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        )
                        unwrapped.append(f"  {rel}:{i}  {stripped[:80]}")

if unwrapped:
    print(f"Found {len(unwrapped)} UNWRAPPED strings:\n")
    for u in unwrapped:
        print(u)
else:
    print("✅ All user-facing strings are wrapped in _()")
