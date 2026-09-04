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


def test_visual_grounding_requires_the_scene():
    scenes, tasks = generate()
    assert all(t['visual_reference'] and t['benchmark_version'] == '2.1-visual-grounded' for t in tasks)
    spatial = [t for t in tasks if t['category'] == 'spatial']
    assert len({t['instruction'] for t in spatial}) == 1
    assert len({tuple(t['ground_truth']) for t in spatial}) > 1
    assert all('最右边' in t['instruction'] and '最左边' in t['instruction'] for t in spatial)


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
