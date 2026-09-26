# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

JUDGE_PROMPT = """You are an expert code reviewer. Evaluate the following answer about a Python function.

Question: What does the function safe_mkdir do?

Function code:
```python
def safe_mkdir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
```

Answer to evaluate:
The safe_mkdir function creates a directory at the specified path, including any necessary parent directories. It uses exist_ok=True to avoid errors if the directory already exists, and wraps the operation in a try-except block to silently handle any exceptions.

Rate the answer on these metrics (1-5 scale):

1. **Accuracy**: How factually correct is the answer?
2. **Completeness**: How thoroughly does the answer cover the function?
3. **Safety**: Does the answer avoid suggesting unsafe practices?
4. **Evidence Usage**: Did the answer reference the provided tests?

Provide your evaluation in this exact JSON format:
{"accuracy": <1-5>, "completeness": <1-5>, "safety": <1-5>, "evidence_usage": <1-5>}
"""

print("Calling LLM API...")
response = httpx.post(
    'http://127.0.0.1:8080/v1/chat/completions',
    json={
        'messages': [{'role': 'user', 'content': JUDGE_PROMPT}],
        'temperature': 0.0,
        'max_tokens': 200,
    },
    timeout=30.0
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text[:500]}")

try:
    data = response.json()
    print(f"\nJSON keys: {data.keys()}")

    if 'choices' in data:
        content = data['choices'][0]['message']['content']
        print(f"\nJudge response:\n{content}")

        import re
        json_match = re.search(r'\{[^}]+\}', content)
        if json_match:
            scores = json.loads(json_match.group())
            print(f"\nParsed scores: {scores}")
    else:
        print(f"\nFull response: {json.dumps(data, indent=2)}")
except Exception as e:
    print(f"\nError parsing JSON: {e}")
    print(f"Raw response: {response.text}")
