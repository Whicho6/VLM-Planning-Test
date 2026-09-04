import argparse
import sys
from src.benchmark import load_benchmark, validate, image_issues

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-images', action='store_true')
    parser.add_argument('--require-verified', action='store_true')
    args = parser.parse_args()
    scenes, tasks = load_benchmark()
    errors = validate(scenes, tasks)
    issues = image_issues(scenes, args.require_verified)
    print(f'数据：{len(scenes)} 个场景，{len(tasks)} 条任务；发现 {len(errors)} 个错误。')
    for issue in errors + issues:
        print(issue)
    raise SystemExit(1 if errors or (issues and (args.require_images or args.require_verified)) else 0)
