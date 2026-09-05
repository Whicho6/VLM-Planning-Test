"""运行完整双提示实验，支持逐条 checkpoint、有限重试和断点续跑。"""
import argparse
import csv
import hashlib
import json
import os
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.benchmark import image_issues, load_benchmark, validate
from src.evaluator import evaluate, summarize
from src.prompts import FREE_FORM, STRUCTURED
from src.utils import ROOT, read_json, write_json
from src.vlm import CompatibleVLM, MockVLM

CATEGORIES = ["single_step", "spatial", "multi_step", "impossible"]
MODES = ["free_form", "structured"]
RETRYABLE = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "network_error_or_timeout")
EVALUATION_VERSION = "3.1"


class CallFailed(RuntimeError):
    def __init__(self, message, attempts, duration):
        super().__init__(message)
        self.attempts = attempts
        self.duration = duration


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def hashes(scenes):
    return {
        "dataset_sha256": {f: hashlib.sha256((ROOT / "data" / f).read_bytes()).hexdigest() for f in ["tasks.json", "scenes.json"]},
        "image_sha256": {s["id"]: hashlib.sha256((ROOT / s["image"]).read_bytes()).hexdigest() for s in scenes},
    }


def empty_evaluation(error):
    return {
        "parsed_output": {"actions": [], "errors": ["api_error"], "unparsed": []},
        "task_planning_success": False, "action_validity": False, "format_compliance": False,
        "hallucination": False, "hallucinated_references": 0, "object_reference_count": 0,
        "failure_type": ["api_error"],
        "simulation": {"state": {}, "events": [], "held": None, "invalid": ["api_error"],
                       "hallucinated_objects": [], "object_references": []},
        "api_error": error,
    }


def call_with_retries(model, image, instruction, mode, backend, max_attempts=3, sleep=time.sleep):
    attempts = 0
    started = time.monotonic()
    while True:
        attempts += 1
        try:
            output = model.plan(image, instruction, mode)
            return output, attempts, time.monotonic() - started, getattr(model, "last_usage", None), getattr(model, "last_request_id", None)
        except Exception as exc:
            if backend == "mock":
                raise
            message = str(exc)
            retryable = isinstance(exc, RuntimeError) and any(marker in message for marker in RETRYABLE)
            if not retryable or attempts >= max_attempts:
                raise CallFailed(message, attempts, time.monotonic() - started) from None
            sleep(2 ** (attempts - 1))


def token_totals(rows):
    totals = {}
    for row in rows:
        usage = row.get("token_usage") or {}
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
    return totals


def update_run_counts(metadata, rows, elapsed, actual_calls=None, model_invocations=None):
    successful_api_calls = sum(not r.get("api_error") for r in rows) if metadata.get("backend") == "real" else 0
    actual_api_calls = sum(int(r.get("api_attempts", 0)) for r in rows) if actual_calls is None else actual_calls
    invocations = sum(int(r.get("api_attempts", 0)) for r in rows) if model_invocations is None else model_invocations
    metadata.update({
        "completed_pairs": len(rows),
        "successful_pairs": sum(not r.get("api_error") for r in rows),
        "failed_pairs": sum(bool(r.get("api_error")) for r in rows),
        "actual_api_calls": actual_api_calls,
        "model_invocations": invocations,
        "successful_api_calls": successful_api_calls,
        "failed_api_calls": max(0, actual_api_calls - successful_api_calls),
        "total_elapsed_seconds": round(elapsed, 3),
        "token_usage": token_totals(rows),
        "updated_at_utc": utc_now(),
    })


def write_summary_csv(path, summary):
    columns = ["scope", "prompt_mode", "category", "total_tasks", "scored_tasks", "api_errors",
               "planning_accuracy", "action_validity", "format_compliance", "hallucination_rate",
               "hallucination_task_rate", "parse_coverage", "object_reference_count"]
    rows = []
    def add(scope, mode, category, values):
        rows.append({"scope": scope, "prompt_mode": mode, "category": category,
                     **{key: values.get(key) for key in columns[3:]}})
    add("overall", "all", "all", summary["overall"])
    for category, values in summary["by_category"].items():
        add("category", "all", category, values)
    for mode, block in summary["by_prompt_mode"].items():
        add("prompt_mode", mode, "all", block["overall"])
        for category, values in block["by_category"].items():
            add("prompt_mode_category", mode, category, values)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def plot(summary, out, label):
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    out.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    method_names = {"free_form": "自由文本", "structured": "结构化动作"}
    category_names = {"single_step": "单步", "spatial": "空间", "multi_step": "多步", "impossible": "不可执行"}
    for offset, (mode, block) in enumerate(summary["by_prompt_mode"].items()):
        values = [block["by_category"][c]["planning_accuracy"] for c in CATEGORIES]
        ax.bar([i + offset * .35 for i in range(4)], values, width=.35, label=method_names[mode])
    ax.set_xticks([i + .175 for i in range(4)], [category_names[c] for c in CATEGORIES])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("规则评测的任务规划成功率")
    ax.set_title(label + "\n各任务类别成功率")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "planning_success.png", dpi=160)
    plt.close(fig)


def finalize(out, rows, metadata, started_monotonic, prior_elapsed, actual_calls, model_invocations):
    summary = summarize(rows)
    write_json(out / "summary.json", {"label": metadata["label"], "metrics": summary})
    write_summary_csv(out / "summary.csv", summary)
    failures = [r for r in rows if not r["task_planning_success"]]
    write_json(out / "failure_cases.json", {"label": metadata["label"], "count": len(failures), "cases": failures})
    plot(summary, out / "figures", metadata["label"])
    metadata["status"] = "completed_with_api_errors" if any(r.get("api_error") for r in rows) else "completed"
    update_run_counts(metadata, rows, prior_elapsed + time.monotonic() - started_monotonic, actual_calls, model_invocations)
    write_json(out / "run_metadata.json", metadata)


def input_image(task, tasks, condition):
    if condition == "text_only":
        return None
    if condition == "shuffled":
        scene_ids = sorted({t["scene_id"] for t in tasks})
        next_scene = scene_ids[(scene_ids.index(task["scene_id"]) + 1) % len(scene_ids)]
        return ROOT / next(t["image"] for t in tasks if t["scene_id"] == next_scene)
    return ROOT / task["image"]


def dry_run(backend="real", resume=None, image_condition="correct", category=None):
    scenes, all_tasks = load_benchmark()
    errors = validate(scenes, all_tasks)
    tasks = [t for t in all_tasks if category is None or t["category"] == category]
    if backend == "real":
        errors += image_issues(scenes, require_verified=True)
        try:
            client = CompatibleVLM()
            model = client.model
            endpoint = client.base_url
        except ValueError as exc:
            errors.append(str(exc))
            model = endpoint = None
    else:
        model, endpoint = "MOCK_ORACLE_NOT_A_VLM", None
    completed = 0
    if resume:
        path = Path(resume) / "raw_results.json"
        if not path.is_file():
            errors.append("续跑目录中缺少 raw_results.json")
        else:
            completed = sum(not r.get("api_error") for r in read_json(path))
    report = {"ok": not errors, "backend": backend, "model": model, "endpoint": endpoint,
              "image_condition": image_condition, "category_filter": category,
              "scenes": len(scenes), "tasks": len(tasks), "planned_pairs": len(tasks) * len(MODES),
              "successful_checkpoint_pairs": completed, "pending_pairs": len(tasks) * len(MODES) - completed,
              "errors": errors}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def run(backend="mock", output=None, resume=None, max_attempts=3, image_condition="correct", category=None):
    if output and resume:
        raise ValueError("--output 与 --resume 不能同时使用。")
    scenes, all_tasks = load_benchmark()
    errors = validate(scenes, all_tasks)
    tasks = [t for t in all_tasks if category is None or t["category"] == category]
    if backend == "real":
        errors += image_issues(scenes, require_verified=True)
    if errors:
        raise ValueError("\n".join(errors))
    model = MockVLM(tasks) if backend == "mock" else CompatibleVLM()
    label = "MOCK / PLACEHOLDER（模拟/占位）" if backend == "mock" else "真实 API 实验"
    data_hashes = hashes(scenes)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(resume) if resume else (Path(output) if output else ROOT / "results" / f"run_{stamp}")
    started = time.monotonic()
    prior_elapsed = 0.0
    if resume:
        if not out.is_dir():
            raise ValueError("续跑目录不存在。")
        metadata = read_json(out / "run_metadata.json")
        rows = read_json(out / "raw_results.json")
        if (metadata.get("backend") != backend or metadata.get("model") != model.model
                or metadata.get("image_condition", "correct") != image_condition
                or metadata.get("category_filter") != category):
            raise ValueError("续跑目录的 backend、模型、图片条件或类别筛选与当前配置不一致。")
        if metadata.get("dataset_sha256") != data_hashes["dataset_sha256"] or metadata.get("image_sha256") != data_hashes["image_sha256"]:
            raise ValueError("数据或图片已变化，不能续跑旧实验。")
        prior_elapsed = float(metadata.get("total_elapsed_seconds", 0))
        actual_calls = int(metadata.get("actual_api_calls", 0))
        model_invocations = int(metadata.get("model_invocations", 0))
    else:
        out.mkdir(parents=True, exist_ok=False)
        rows = []
        metadata = {"label": label, "backend": backend, "model": model.model, "endpoint": getattr(model, "base_url", None),
                    "created_at_utc": utc_now(), "status": "running", "seed": 42, "image_condition": image_condition,
                    "category_filter": category,
                    "evaluation_version": EVALUATION_VERSION,
                    "benchmark_version": tasks[0].get("benchmark_version"),
                    "temperature": 0, "max_tokens": 512, "max_attempts_per_pair": max_attempts,
                    "prompts": {"free_form": FREE_FORM, "structured": STRUCTURED}, **data_hashes,
                    "python": platform.python_version(),
                    "code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted((ROOT / "src").glob("*.py")) + [ROOT / "run_evaluation.py", ROOT / "requirements-lock.txt"]}}
        update_run_counts(metadata, rows, 0)
        write_json(out / "run_metadata.json", metadata)
        write_json(out / "raw_results.json", rows)
        actual_calls = 0
        model_invocations = 0
    lookup = {s["id"]: s for s in scenes}
    order = [(t, mode) for t in tasks for mode in MODES]
    random.Random(42).shuffle(order)
    successful = {(r["task_id"], r["prompt_mode"]) for r in rows if not r.get("api_error")}
    row_by_key = {(r["task_id"], r["prompt_mode"]): r for r in rows}
    try:
        for task, mode in order:
            key = (task["id"], mode)
            if key in successful:
                continue
            base = {"task_id": task["id"], "scene_id": task["scene_id"], "image": task["image"],
                    "image_condition": image_condition,
                    "instruction": task["instruction"], "category": task["category"], "prompt_mode": mode,
                    "benchmark_version": task.get("benchmark_version"),
                    "existence_decision": task.get("existence_decision"),
                    "spatial_decision": task.get("spatial_decision"),
                    "multi_step_decision": task.get("multi_step_decision"),
                    "scene_objects": task["objects"], "ground_truth": task["ground_truth"], "target_state": task["target_state"],
                    "model": model.model, "api_error": None, "started_at_utc": utc_now()}
            try:
                actual_image = input_image(task, tasks, image_condition)
                base["actual_input_image"] = None if actual_image is None else str(actual_image.relative_to(ROOT)).replace('\\', '/')
                raw, attempts, duration, usage, request_id = call_with_retries(
                    model, actual_image, task["instruction"], mode, backend, max_attempts=max_attempts)
                row = {**base, "raw_model_output": raw, **evaluate(task, lookup[task["scene_id"]], raw, mode),
                       "api_attempts": attempts, "duration_seconds": round(duration, 3), "token_usage": usage,
                       "provider_request_id": request_id, "completed_at_utc": utc_now()}
            except Exception as exc:
                attempts = exc.attempts if isinstance(exc, CallFailed) else 1
                duration = exc.duration if isinstance(exc, CallFailed) else None
                row = {**base, "raw_model_output": None, **empty_evaluation(str(exc)), "api_attempts": attempts,
                       "duration_seconds": round(duration, 3) if duration is not None else None,
                       "token_usage": None, "provider_request_id": None,
                       "completed_at_utc": utc_now()}
            row_by_key[key] = row
            attempts_used = int(row.get("api_attempts", 0))
            model_invocations += attempts_used
            if backend == "real":
                actual_calls += attempts_used
            rows = [row_by_key[(t["id"], m)] for t, m in order if (t["id"], m) in row_by_key]
            write_json(out / "raw_results.json", rows)
            update_run_counts(metadata, rows, prior_elapsed + time.monotonic() - started, actual_calls, model_invocations)
            write_json(out / "run_metadata.json", metadata)
    except KeyboardInterrupt:
        metadata["status"] = "interrupted"
        update_run_counts(metadata, rows, prior_elapsed + time.monotonic() - started, actual_calls, model_invocations)
        write_json(out / "run_metadata.json", metadata)
        print(f"实验已中断；已保存 checkpoint：{out}")
        raise
    finalize(out, rows, metadata, started, prior_elapsed, actual_calls, model_invocations)
    print(f"{label}\n结果目录：{out}\n完成 {len(rows)}/80；实际调用 {metadata['actual_api_calls']} 次；状态：{metadata['status']}")
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["mock", "real"], default="mock")
    parser.add_argument("--output", help="新结果目录；不能已存在。")
    parser.add_argument("--resume", help="续跑已有结果目录；成功的任务不会重复调用。")
    parser.add_argument("--max-attempts", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--dry-run", action="store_true", help="只检查数据、照片和配置，不调用 API。")
    parser.add_argument("--image-condition", choices=["correct", "text_only", "shuffled"], default="correct",
                        help="模型接收正确图片、无图片或确定性错配图片。每次运行只使用一种条件。")
    parser.add_argument("--category", choices=CATEGORIES,
                        help="只运行一个任务类别；省略时运行全部 40 条任务。")
    args = parser.parse_args()
    try:
        if args.dry_run:
            raise SystemExit(0 if dry_run(args.backend, args.resume, args.image_condition, args.category)["ok"] else 1)
        run(args.backend, args.output, args.resume, args.max_attempts, args.image_condition, args.category)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc))
