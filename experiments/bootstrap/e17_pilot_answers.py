# -*- coding: utf-8 -*-
"""E17 Pilot: LLM Answer Generation

Generates answers for each function in the modes present in the pilot data.
Current design (2026-09-22): 3 modes — A (code only), B (specific runtime
TESTS), D (coverage-matched decoy). The old C (static) mode was dropped because
it was never implemented and was identical to A.
"""
import json
import sys
from pathlib import Path
from typing import Dict, List

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from e17_extract import read_function_code, read_tests  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def build_prompt(question: str, code: str, tests: List[str]) -> str:
    """Build prompt for LLM. ``tests`` are names; unresolved ones are skipped."""
    prompt = f"""You are an expert Python developer. Answer the following question about a function in a codebase.

Question: {question}

Function code:
```python
{code}
```
"""
    bodies = read_tests(tests)
    if bodies:
        prompt += "\nRelevant tests that exercise this function:\n"
        for body in bodies:
            prompt += f"\n```python\n{body}\n```\n"

    prompt += "\nProvide a clear, accurate explanation of what the function does, its purpose, inputs, outputs, and any edge cases it handles."

    return prompt


def call_llm(prompt: str, temperature: float = 0.0) -> str:
    """Call LLM API (llama.cpp on port 8080)."""
    try:
        response = httpx.post(
            'http://127.0.0.1:8080/v1/chat/completions',
            json={
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': temperature,
                'max_tokens': 1000,
            },
            timeout=60.0
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"# Error calling LLM: {e}"


def generate_answers(experiment_data: Dict) -> Dict:
    """Generate answers for all questions in all modes."""
    results = {
        'metadata': experiment_data['metadata'],
        'answers': []
    }

    for func_data in experiment_data['functions']:
        print(f"\nProcessing {func_data['name']}...")

        # Read function code
        code = read_function_code(func_data['file_path'], func_data['name'])
        if not code:
            print(f"  SKIP: could not extract source for {func_data['name']}")
            continue
        question = func_data['question']

        func_result = {
            'id': func_data['id'],
            'name': func_data['name'],
            'file_path': func_data['file_path'],
            'question': question,
            'modes': {}
        }

        for mode_name, mode_data in func_data['modes'].items():
            tests = mode_data['tests']
            print(f"  {mode_name} ({len(tests)} tests)...")
            prompt = build_prompt(question, code, tests)
            answer = call_llm(prompt)
            func_result['modes'][mode_name] = {
                'prompt': prompt,
                'answer': answer,
                'tests': tests,
            }

        results['answers'].append(func_result)

    return results


def main():
    print("=" * 80)
    print("E17 PILOT: LLM ANSWER GENERATION")
    print("=" * 80)

    # Load experiment data
    data_path = Path(__file__).parent / "e17_pilot_data.json"
    with open(data_path, 'r', encoding='utf-8') as f:
        experiment_data = json.load(f)

    print(f"Loaded {len(experiment_data['functions'])} functions")

    # Generate answers
    results = generate_answers(experiment_data)

    # Save results
    output_path = Path(__file__).parent / "e17_pilot_answers.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 80}")
    print(f"Answers saved to: {output_path}")
    print(f"Total answers: {len(results['answers'])} × 4 modes = {len(results['answers']) * 4}")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
