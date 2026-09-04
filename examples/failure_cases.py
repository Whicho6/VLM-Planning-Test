"""Synthetic parser/evaluator regression examples, never VLM observations."""
from src.benchmark import load_benchmark
from src.evaluator import evaluate
from src.utils import ROOT, write_json


def main():
    scenes, tasks = load_benchmark()
    multi = tasks[2]['ground_truth']
    cases = [(0, 'PICK(calculator)', 'object hallucination'),
             (0, 'FLY(tissue)', 'invalid action'),
             (0, 'PICK tissue', 'parsing failure'),
             (1, 'PICK(mouse)\nPLACE_LEFT(mouse, eraser)', 'incorrect spatial relation'),
             (2, '\n'.join(multi[2:] + multi[:2]), 'wrong action order'),
             (3, 'PICK(mouse)', 'failure to reject impossible task')]
    rows = [{'label': 'SYNTHETIC TEST FIXTURE - NOT VLM OUTPUT', 'case': name,
             'task_id': tasks[i]['id'], 'raw_output': output,
             **evaluate(tasks[i], scenes[0], output, 'structured')} for i, output, name in cases]
    write_json(ROOT / 'examples/synthetic_failures.json', rows)
    print(f'Saved {len(rows)} synthetic failure fixtures.')


if __name__ == '__main__':
    main()
