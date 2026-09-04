"""在终端显示某次实验的总体、分类和提示模式结果。"""
import argparse
import json
import sys
from pathlib import Path
from src.utils import ROOT, read_json

NAMES = {"single_step": "单步", "spatial": "空间", "multi_step": "多步", "impossible": "不可执行",
         "free_form": "自由文本", "structured": "结构化动作"}


def percent(value):
    return "N/A" if value is None else f"{value * 100:.2f}%"


def print_metrics(values, indent=""):
    print(f"{indent}Planning Accuracy: {percent(values.get('planning_accuracy'))}")
    print(f"{indent}Action Validity: {percent(values.get('action_validity'))}")
    print(f"{indent}Format Compliance: {percent(values.get('format_compliance'))}")
    print(f"{indent}Hallucination Rate: {percent(values.get('hallucination_rate'))}")
    print(f"{indent}API Errors: {values.get('api_errors', 0)} / {values.get('total_tasks', 0)}")


def latest_result():
    candidates = [p for p in (ROOT / "results").glob("run_*") if (p / "summary.json").is_file()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def show(path):
    path = Path(path)
    summary_doc = read_json(path / "summary.json")
    summary = summary_doc["metrics"]
    metadata = read_json(path / "run_metadata.json")
    print(f"结果目录: {path.resolve()}")
    print(f"状态: {metadata.get('status')} | 模型: {metadata.get('model')} | 图片条件: {metadata.get('image_condition', 'correct')}")
    print(f"模型调用: {metadata.get('model_invocations')} | 实际 API 调用: {metadata.get('actual_api_calls')} | API成功: {metadata.get('successful_api_calls')} | API失败: {metadata.get('failed_api_calls')} | 总耗时: {metadata.get('total_elapsed_seconds')} 秒")
    if metadata.get("token_usage"):
        print("Token Usage: " + json.dumps(metadata["token_usage"], ensure_ascii=False))
    print("\nOverall Results")
    print_metrics(summary["overall"])
    print("\nBy Category")
    for category, values in summary["by_category"].items():
        print(f"{NAMES[category]}:")
        print_metrics(values, "  ")
    print("\nBy Prompt Mode")
    for mode, block in summary["by_prompt_mode"].items():
        print(f"{NAMES[mode]}:")
        print_metrics(block["overall"], "  ")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", nargs="?", help="结果目录；省略时读取最新的 run_* 完整结果。")
    args = parser.parse_args()
    selected = Path(args.result_dir) if args.result_dir else latest_result()
    if selected is None:
        raise SystemExit("没有找到可显示的 run_* 结果目录。")
    try:
        show(selected)
    except (OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"无法读取结果：{exc}")
