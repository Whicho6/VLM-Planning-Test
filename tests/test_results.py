import json
from pathlib import Path

import run_evaluation
from src.utils import read_json, write_json
from src.vlm import MockVLM


REQUIRED = {"task_id", "scene_id", "image", "image_condition", "actual_input_image", "instruction", "category", "prompt_mode", "benchmark_version", "existence_decision", "spatial_decision", "multi_step_decision", "ground_truth",
            "raw_model_output", "parsed_output", "task_planning_success", "action_validity",
            "format_compliance", "hallucination", "hallucinated_references", "failure_type", "simulation"}


def test_result_files_and_required_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evaluation, "plot", lambda *args: None)
    out = run_evaluation.run("mock", output=tmp_path / "run")
    assert {"raw_results.json", "summary.json", "summary.csv", "failure_cases.json", "run_metadata.json"} <= {p.name for p in out.iterdir()}
    rows = read_json(out / "raw_results.json")
    assert len(rows) == 80 and REQUIRED <= set(rows[0])
    summary = read_json(out / "summary.json")["metrics"]
    assert {"overall", "by_category", "by_prompt_mode"} <= set(summary)
    assert set(summary["by_prompt_mode"]) == {"free_form", "structured"}
    assert read_json(out / "failure_cases.json")["cases"] == []
    metadata = read_json(out / "run_metadata.json")
    assert metadata["actual_api_calls"] == 0 and metadata["model_invocations"] == 80
    assert metadata["benchmark_version"] == "3.1-visual-counterfactual"


def test_resume_skips_successful_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evaluation, "plot", lambda *args: None)
    out = run_evaluation.run("mock", output=tmp_path / "run")
    rows = read_json(out / "raw_results.json")
    removed = rows.pop()
    write_json(out / "raw_results.json", rows)
    calls = []
    class CountingMock(MockVLM):
        def plan(self, *args, **kwargs):
            calls.append((args, kwargs))
            return super().plan(*args, **kwargs)
    monkeypatch.setattr(run_evaluation, "MockVLM", CountingMock)
    run_evaluation.run("mock", resume=out)
    assert len(calls) == 1
    restored = read_json(out / "raw_results.json")
    assert len(restored) == 80
    metadata = read_json(out / "run_metadata.json")
    assert metadata["actual_api_calls"] == 0 and metadata["model_invocations"] == 81
    assert any(r["task_id"] == removed["task_id"] and r["prompt_mode"] == removed["prompt_mode"] for r in restored)


def test_retry_is_bounded_and_captures_usage():
    class Flaky:
        last_usage = None
        last_request_id = None
        def __init__(self): self.calls = 0
        def plan(self, *args):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("HTTP 503")
            self.last_usage = {"total_tokens": 12}
            self.last_request_id = "request-test"
            return "PICK(tissue)"
    model = Flaky()
    result = run_evaluation.call_with_retries(model, "image", "instruction", "structured", "real", max_attempts=3, sleep=lambda _: None)
    assert result[0] == "PICK(tissue)" and result[1] == 3
    assert result[3] == {"total_tokens": 12} and result[4] == "request-test"


def test_nonretryable_failure_is_one_call():
    class Bad:
        def __init__(self): self.calls = 0
        def plan(self, *args):
            self.calls += 1
            raise ValueError("bad response")
    model = Bad()
    try:
        run_evaluation.call_with_retries(model, "image", "instruction", "structured", "real", sleep=lambda _: None)
    except run_evaluation.CallFailed as exc:
        assert exc.attempts == 1 and model.calls == 1
    else:
        raise AssertionError("Expected CallFailed")


def test_image_conditions_are_deterministic():
    _, tasks = run_evaluation.load_benchmark()
    task = tasks[0]
    assert run_evaluation.input_image(task, tasks, 'text_only') is None
    assert run_evaluation.input_image(task, tasks, 'correct').name == 'scene_01.jpg'
    assert run_evaluation.input_image(task, tasks, 'shuffled').name == 'scene_02.jpg'


def test_api_failures_are_saved_with_complete_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evaluation, "plot", lambda *args: None)
    class Offline:
        model = "offline-test-model"
        base_url = "https://example.invalid/v1"
        last_usage = None
        last_request_id = None
        def plan(self, *args):
            raise ValueError("offline fixture")
    monkeypatch.setattr(run_evaluation, "CompatibleVLM", Offline)
    out = run_evaluation.run("real", output=tmp_path / "failed", max_attempts=1)
    rows = read_json(out / "raw_results.json")
    assert len(rows) == 80 and all(REQUIRED <= set(row) for row in rows)
    assert all(row["api_error"] == "offline fixture" for row in rows)
    assert len(read_json(out / "failure_cases.json")["cases"]) == 80
    metadata = read_json(out / "run_metadata.json")
    assert metadata["actual_api_calls"] == 80
    assert metadata["successful_api_calls"] == 0 and metadata["failed_api_calls"] == 80


def test_category_filter_runs_only_spatial_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evaluation, "plot", lambda *args: None)
    out = run_evaluation.run("mock", output=tmp_path / "spatial", category="spatial")
    rows = read_json(out / "raw_results.json")
    assert len(rows) == 20
    assert {row["category"] for row in rows} == {"spatial"}
    metadata = read_json(out / "run_metadata.json")
    assert metadata["category_filter"] == "spatial"
    assert metadata["model_invocations"] == 20
