"""Generate metadata once. Refuse to replace existing annotations."""
from src.benchmark import generate, validate
from src.utils import ROOT, write_json

if __name__ == '__main__':
    if any((ROOT / f'data/{name}.json').exists() for name in ['scenes', 'tasks']):
        raise SystemExit('数据文件已存在，为避免覆盖人工标注，程序已停止。')
    scenes, tasks = generate()
    errors = validate(scenes, tasks)
    if errors:
        raise SystemExit('\n'.join(errors))
    write_json(ROOT / 'data/scenes.json', scenes)
    write_json(ROOT / 'data/tasks.json', tasks)
    for s in scenes:
        path = ROOT / (s['image'] + '.placeholder.txt')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('PLACEHOLDER ONLY — NOT AN IMAGE\nPhotograph left to right: ' + ', '.join(s['objects']) + '\n' + s['initial_state'], encoding='utf-8')
    print('已生成 10 个场景和 40 条已校验任务；没有生成照片或真实实验结果。')
