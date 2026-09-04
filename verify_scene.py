"""Record the user's visual inspection, tied to exact image bytes."""
import argparse
from hashlib import sha256
from src.benchmark import load_benchmark, image_issues
from src.utils import ROOT, write_json

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='After visually checking every photo against README, attest its object inventory and layout.')
    p.add_argument('--scene', default='all')
    p.add_argument('--confirm-objects-and-layout', action='store_true', required=True)
    args = p.parse_args()
    scenes, _ = load_benchmark()
    selected = [s for s in scenes if args.scene == 'all' or s['id'] == args.scene]
    if not selected:
        raise SystemExit('未知场景。')
    issues = image_issues(selected)
    if issues:
        raise SystemExit('\n'.join(issues))
    for scene in selected:
        scene['annotation_status'] = 'verified_real'
        scene['verified_image_sha256'] = sha256((ROOT / scene['image']).read_bytes()).hexdigest()
    write_json(ROOT / 'data/scenes.json', scenes)
    print(f'已记录 {len(selected)} 张照片的人工核对状态。这是人工声明，不是自动物体识别。')
