import copy
import pytest
from src.benchmark import generate
from src.evaluator import evaluate, metrics

SCENES, TASKS = generate()


@pytest.mark.parametrize('method', ['structured', 'free_form'])
def test_all_ground_truth(method):
    from src.vlm import MockVLM
    model = MockVLM(TASKS)
    for t in TASKS:
        scene = next(s for s in SCENES if s['id'] == t['scene_id'])
        assert evaluate(t, scene, model.plan(t['image'], t['instruction'], method), method)['task_planning_success']


@pytest.mark.parametrize('output,failure', [('PICK(calculator)', 'object_hallucination'), ('PLACE_IN(tissue, mouse)', 'invalid_precondition'), ('PICK(tissue)\nPICK(mouse)', 'hand_occupied'), ('PICK(mouse)', 'incorrect_target_state'), ('INVALID_TASK', 'incorrect_target_state')])
def test_wrong_plans(output, failure):
    result = evaluate(TASKS[0], SCENES[0], output, 'structured')
    assert not result['task_planning_success']
    assert failure in result['failure_type']


def test_equivalent_non_exact_plan():
    output = 'PICK(mouse)\nPLACE_RIGHT(mouse, eraser)\nPICK(tissue)'
    assert evaluate(TASKS[0], SCENES[0], output, 'structured')['task_planning_success']


def test_order_and_impossible():
    t = TASKS[2]
    gt = t['ground_truth']
    result = evaluate(t, SCENES[0], '\n'.join(gt[2:] + gt[:2]), 'structured')
    assert 'invalid_precondition' in result['failure_type']
    assert not evaluate(TASKS[3], SCENES[0], 'PICK(mouse)', 'structured')['task_planning_success']


def test_metrics_denominators():
    good = evaluate(TASKS[0], SCENES[0], '\n'.join(TASKS[0]['ground_truth']), 'structured')
    bad = evaluate(TASKS[0], SCENES[0], 'PICK(calculator)', 'structured')
    result = metrics([good, bad])
    assert result['task_planning_success'] == .5
    assert result['object_hallucination_rate'] == .5
    assert result['hallucination_task_rate'] == .5
    assert metrics([])['object_hallucination_rate'] is None
    assert metrics([{'api_error': 'HTTPError', 'failure_type': ['api_error']}])['task_planning_success'] == 0


def test_format_separate_from_semantics():
    r = evaluate(TASKS[0], SCENES[0], 'I would somehow do it.', 'free_form')
    assert r['response_nonempty'] and not r['format_compliance'] and not r['action_validity'] and not r['task_planning_success']
