from copy import deepcopy
from pathlib import Path
from PIL import Image
from src.benchmark import generate, validate, image_issues


def test_metadata_and_mutations():
    scenes, tasks = generate()
    assert not validate(scenes, tasks)
    for field, value in [('instruction', '随意移动物体。'), ('objects', ['calculator']), ('ground_truth', ['INVALID_TASK']), ('target_state', [])]:
        changed = deepcopy(tasks)
        changed[0][field] = value
        assert validate(scenes, changed)


def test_visual_grounding_requires_opposite_condition_branches():
    scenes, tasks = generate()
    assert all(t['visual_reference'] and t['benchmark_version'] == '3.1-visual-counterfactual' for t in tasks)
    spatial = [t for t in tasks if t['category'] == 'spatial']
    groups = {text: [t for t in spatial if t['instruction'] == text]
              for text in {t['instruction'] for t in spatial}}
    assert len(groups) == 5
    for group in groups.values():
        assert len(group) == 2
        assert {t['spatial_decision']['observed'] for t in group} == {True, False}
        assert {t['spatial_decision']['selected_branch'] for t in group} == {'if', 'else'}
        assert {t['spatial_decision']['placement'] for t in group} == {'left', 'right'}
        assert len({tuple(t['ground_truth']) for t in group}) == 2



def test_all_categories_require_the_image_for_the_answer():
    scenes, tasks = generate()
    existence = [t for t in tasks if t['category'] in {'single_step', 'impossible'}]
    pairs = {}
    for task in existence:
        pairs.setdefault(task['existence_decision']['pair_id'], []).append(task)
    assert len(pairs) == 10
    for pair in pairs.values():
        assert len(pair) == 2
        assert len({t['instruction'] for t in pair}) == 1
        assert {t['existence_decision']['observed'] for t in pair} == {True, False}
        assert {t['category'] for t in pair} == {'single_step', 'impossible'}
        assert len({tuple(t['ground_truth']) for t in pair}) == 2

    multi = [t for t in tasks if t['category'] == 'multi_step']
    groups = {text: [t for t in multi if t['instruction'] == text]
              for text in {t['instruction'] for t in multi}}
    assert len(groups) == 5
    for pair in groups.values():
        assert len(pair) == 2
        assert {t['multi_step_decision']['observed'] for t in pair} == {True, False}
        assert {t['multi_step_decision']['placement'] for t in pair} == {'left', 'right'}
        assert len({tuple(t['ground_truth']) for t in pair}) == 2

def test_spatial_metadata_is_checked_against_layout():
    scenes, tasks = generate()
    changed = deepcopy(tasks)
    spatial = next(t for t in changed if t['category'] == 'spatial')
    spatial['spatial_decision']['observed'] = not spatial['spatial_decision']['observed']
    assert any('空间条件与场景不一致' in error for error in validate(scenes, changed))


def test_missing_corrupt_unverified_and_changed_images(tmp_path):
    from hashlib import sha256
    scenes, _ = generate()
    scene = scenes[0]
    assert '缺少图片' in image_issues([scene], root=tmp_path)[0]
    path = tmp_path / scene['image']
    path.parent.mkdir(parents=True)
    path.write_text('PLACEHOLDER')
    assert '损坏' in image_issues([scene], root=tmp_path)[0]
    Image.new('RGB', (20, 20)).save(path)
    assert image_issues([scene], True, tmp_path)
    scene['annotation_status'] = 'verified_real'
    scene['verified_image_sha256'] = sha256(path.read_bytes()).hexdigest()
    assert not image_issues([scene], True, tmp_path)
    Image.new('RGB', (30, 30)).save(path)
    assert image_issues([scene], True, tmp_path)


def test_real_run_blocked_before_model_init(monkeypatch, tmp_path):
    import pytest
    import run_evaluation
    def forbidden_init():
        raise AssertionError('Must not initialize API with missing photos')
    monkeypatch.setattr(run_evaluation, 'CompatibleVLM', forbidden_init)
    monkeypatch.setattr(run_evaluation, 'image_issues', lambda *a, **kw: ['缺少图片'])
    with pytest.raises(ValueError, match='缺少图片'):
        run_evaluation.run('real', tmp_path / 'real')
    assert not (tmp_path / 'real').exists()
