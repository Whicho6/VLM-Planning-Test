import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from src.benchmark import load_benchmark, image_issues
from src.evaluator import evaluate
from src.parser import parse_structured, parse_free_form
from src.vlm import MockVLM, CompatibleVLM
from src.utils import ROOT
from src.utils import write_json

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('--backend', choices=['mock', 'real'], default='mock')
    p.add_argument('--task-id', default='task_001')
    p.add_argument('--image')
    p.add_argument('--instruction')
    p.add_argument('--mode', choices=['free_form', 'structured'], default='structured')
    p.add_argument('--save', action='store_true', help='把本次 demo 原始输出和评测结果保存到独立目录。')
    args = p.parse_args()
    scenes, tasks = load_benchmark()
    task = next((t for t in tasks if t['id'] == args.task_id), None)
    if task is None:
        raise SystemExit('未知任务 ID。')
    if bool(args.image) != bool(args.instruction):
        raise SystemExit('请同时提供 --image 和 --instruction，或直接使用 --task-id。')
    image = Path(args.image) if args.image else ROOT / task['image']
    instruction = args.instruction or task['instruction']
    scene = next((s for s in scenes if (ROOT / s['image']).resolve() == image.resolve()), None)
    if args.backend == 'real':
        if scene is None:
            raise SystemExit('真实演示只能使用已经登记并核对的 benchmark 照片。')
        issues = image_issues([scene], True)
        if issues:
            raise SystemExit('\n'.join(issues))
    try:
        model = MockVLM(tasks) if args.backend == 'mock' else CompatibleVLM()
        started = time.monotonic()
        output = model.plan(image, instruction, args.mode)
        duration = time.monotonic() - started
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
    exact_task = next((t for t in tasks if (ROOT / t['image']).resolve() == image.resolve() and t['instruction'] == instruction), None)
    print('MOCK / PLACEHOLDER（模拟/占位）' if args.backend == 'mock' else '真实 API')
    print(f'场景：{image}\n指令：{instruction}\n模型输出：\n{output}')
    result = evaluate(exact_task, scene, output, args.mode) if exact_task and scene else (parse_structured if args.mode == 'structured' else parse_free_form)(output)
    print('解析动作 / 校验结果：\n' + json.dumps(result, indent=2, ensure_ascii=False))
    if args.save:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        out = ROOT / 'results' / f'demo_{stamp}'
        record = {'backend': args.backend, 'model': model.model, 'task_id': exact_task['id'] if exact_task else None,
                  'scene_id': exact_task['scene_id'] if exact_task else None, 'image': str(image),
                  'instruction': instruction, 'prompt_mode': args.mode,
                  'ground_truth': exact_task['ground_truth'] if exact_task else None,
                  'raw_model_output': output, **result, 'duration_seconds': round(duration, 3),
                  'token_usage': getattr(model, 'last_usage', None),
                  'provider_request_id': getattr(model, 'last_request_id', None)}
        write_json(out / 'demo_result.json', record)
        print(f'本次结果已保存到：{out / "demo_result.json"}')
