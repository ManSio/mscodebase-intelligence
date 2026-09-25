# -*- coding: utf-8 -*-
"""E17 Pilot: Judge Evaluation

Evaluates answers using LLM-as-judge with:
- 4 metrics: accuracy, completeness, safety, evidence_usage
- Position randomization (tests block before/after the answer)
- Multiple trials for stability
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from e17_extract import read_function_code, read_tests  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


JUDGE_PROMPT = """You are an expert code reviewer. Evaluate the following answer about a Python function.

Question: {question}

Function code:
```python
{code}
```

{first_block}
{second_block}
Rate the answer on these metrics (1-5 scale):

1. **Accuracy**: How factually correct is the answer? Does it accurately describe what the function does?
   1 = Completely wrong
   2 = Mostly wrong with some correct elements
   3 = Partially correct, significant errors
   4 = Mostly correct, minor errors
   5 = Completely accurate

2. **Completeness**: How thoroughly does the answer cover the function's purpose, inputs, outputs, and edge cases?
   1 = Very incomplete, missing key information
   2 = Incomplete, missing important aspects
   3 = Moderately complete
   4 = Mostly complete
   5 = Very comprehensive

3. **Safety**: Does the answer avoid suggesting unsafe practices or misunderstandings?
   1 = Suggests dangerous practices
   2 = Contains unsafe recommendations
   3 = Neutral, neither safe nor unsafe
   4 = Generally safe
   5 = Very safe, no concerns

4. **Evidence Usage**: Did the answer reference or use the provided tests to inform the explanation?
   1 = Completely ignored the tests
   2 = Mentioned tests but didn't use them
   3 = Partially used tests
   4 = Used tests effectively
   5 = Explicitly referenced tests and used them to explain behavior

Provide your evaluation in this exact JSON format:
{{"accuracy": <1-5>, "completeness": <1-5>, "safety": <1-5>, "evidence_usage": <1-5>}}
"""


def call_judge(prompt: str, temperature: float = 0.0) -> Dict[str, int]:
    """Call LLM judge and parse scores."""
    try:
        response = httpx.post(
            'http://127.0.0.1:8080/v1/chat/completions',
            json={
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': temperature,
                'max_tokens': 200,
            },
            timeout=30.0
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']

        # Parse JSON from response
        # Find JSON block
        import re
        json_match = re.search(r'\{[^}]+\}', content)
        if json_match:
            scores = json.loads(json_match.group())
            return {
                'accuracy': scores.get('accuracy', 3),
                'completeness': scores.get('completeness', 3),
                'safety': scores.get('safety', 3),
                'evidence_usage': scores.get('evidence_usage', 3),
            }
        else:
            return {'accuracy': 3, 'completeness': 3, 'safety': 3, 'evidence_usage': 3}
    except Exception as e:
        print(f"    Judge error: {e}")
        return {'accuracy': 3, 'completeness': 3, 'safety': 3, 'evidence_usage': 3}


def build_judge_prompt(
    question: str,
    code: str,
    answer: str,
    tests: List[str],
    tests_first: bool,
) -> str:
    """Build judge prompt; ``tests_first`` controls the block order."""
    bodies = read_tests(tests)
    tests_section = ""
    if bodies:
        tests_section = "Relevant tests:\n"
        for body in bodies:
            tests_section += f"\n```python\n{body}\n```\n"

    answer_block = f"Answer to evaluate:\n{answer}\n"
    if tests_section and tests_first:
        first_block, second_block = tests_section, answer_block
    else:
        first_block, second_block = answer_block, tests_section

    return JUDGE_PROMPT.format(
        question=question,
        code=code,
        first_block=first_block,
        second_block=second_block,
    )


def judge_single_answer(
    question: str,
    code: str,
    answer: str,
    tests: List[str],
    n_trials: int = 11
) -> Dict[str, List[int]]:
    """Judge a single answer with multiple trials and randomized block order."""
    all_scores = defaultdict(list)

    for trial in range(n_trials):
        tests_first = random.random() < 0.5
        prompt = build_judge_prompt(question, code, answer, tests, tests_first)
        scores = call_judge(prompt)
        for metric, score in scores.items():
            all_scores[metric].append(score)

    return dict(all_scores)


def evaluate_all_answers(answers_data: Dict, n_trials: int = 11) -> Dict:
    """Evaluate all answers."""
    results = {
        'metadata': answers_data['metadata'],
        'evaluations': []
    }

    for answer_data in answers_data['answers']:
        print(f"\nEvaluating {answer_data['name']}...")

        code = read_function_code(answer_data['file_path'], answer_data['name']) or ""
        question = answer_data['question']

        func_eval = {
            'id': answer_data['id'],
            'name': answer_data['name'],
            'evaluations': {}
        }

        for mode_name, mode_data in answer_data['modes'].items():
            print(f"  {mode_name}...")
            answer = mode_data['answer']
            tests = mode_data['tests']

            scores = judge_single_answer(question, code, answer, tests, n_trials)

            # Calculate mean and std
            eval_result = {}
            for metric, values in scores.items():
                mean_val = sum(values) / len(values)
                eval_result[metric] = {
                    'mean': round(mean_val, 2),
                    'values': values
                }
                print(f"    {metric}: {mean_val:.2f} (std: {(sum((v - mean_val)**2 for v in values) / len(values))**0.5:.2f})")

            func_eval['evaluations'][mode_name] = eval_result

        results['evaluations'].append(func_eval)

    return results


def main():
    print("=" * 80)
    print("E17 PILOT: JUDGE EVALUATION")
    print("=" * 80)

    # Load answers
    answers_path = Path(__file__).parent / "e17_pilot_answers.json"
    with open(answers_path, 'r', encoding='utf-8') as f:
        answers_data = json.load(f)

    print(f"Loaded {len(answers_data['answers'])} answers")

    # Evaluate
    results = evaluate_all_answers(answers_data, n_trials=11)

    # Save results
    output_path = Path(__file__).parent / "e17_pilot_evaluations.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 80}")
    print(f"Evaluations saved to: {output_path}")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
