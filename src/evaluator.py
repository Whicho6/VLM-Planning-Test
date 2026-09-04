from collections import Counter
from src.parser import ARITY, parse_structured, parse_free_form


def simulate(actions: list, scene: dict) -> dict:
    objects = set(scene["objects"])
    held = None
    state = {r["object"]: (r["relation"], r["target"]) for r in scene["relations"]}
    events, invalid = [], []
    hallucinated, refs = [], []
    for a in actions:
        name, args = a["action"], a["args"]
        refs.extend(args)
        hallucinated.extend(x for x in args if x not in objects)
        if name not in ARITY or len(args) != ARITY.get(name):
            invalid.append("illegal_action")
            continue
        if name == "INVALID_TASK":
            if len(actions) != 1:
                invalid.append("mixed_rejection")
            continue
        if any(x not in objects for x in args):
            invalid.append("object_hallucination")
            continue
        obj = args[0]
        if name == "PICK":
            if held is not None:
                invalid.append("hand_occupied")
            else:
                held = obj
                state.pop(obj, None)
        elif held != obj or obj == args[1] or (name == "PLACE_IN" and args[1] not in scene["containers"]):
            invalid.append("invalid_precondition")
        else:
            state[obj] = (name.removeprefix("PLACE_").lower(), args[1])
            events.append((obj, *state[obj]))
            held = None
    return {"state": state, "events": events, "held": held, "invalid": invalid,
            "hallucinated_objects": hallucinated, "object_references": refs}


def evaluate(task: dict, scene: dict, output: str, method: str) -> dict:
    parsed = (parse_structured if method == "structured" else parse_free_form)(output)
    sim = simulate(parsed["actions"], scene)
    rejected = parsed["actions"] == [{"action": "INVALID_TASK", "args": []}]
    valid = not parsed["errors"] and not sim["invalid"]
    goals = [(g["object"], g["relation"], g["target"]) for g in task["target_state"]]
    final_ok = all((sim["held"] == o) if r == "held" else sim["state"].get(o) == (r, t) for o, r, t in goals)
    cursor = 0
    for event in sim["events"]:
        if cursor < len(goals) and event == goals[cursor]:
            cursor += 1
    ordered = cursor == len([g for g in goals if g[1] != 'held'])
    expects_held = any(r == 'held' for _, r, _ in goals)
    gripper_ok = expects_held or sim["held"] is None
    success = valid and (rejected if task["category"] == "impossible" else not rejected and final_ok and ordered and gripper_ok)
    failures = list(dict.fromkeys(parsed["errors"] + sim["invalid"]))
    if not success and not failures:
        failures.append("failure_to_reject_impossible" if task["category"] == "impossible" else "wrong_action_order" if final_ok and not ordered else "incorrect_target_state")
    return {"parsed_output": parsed, "task_planning_success": success, "action_validity": valid,
            "format_compliance": not parsed["errors"], "response_nonempty": bool(output.strip()),
            "hallucination": bool(sim["hallucinated_objects"]),
            "hallucinated_references": len(sim["hallucinated_objects"]), "object_reference_count": len(sim["object_references"]),
            "failure_type": failures, "simulation": sim}


def metrics(rows: list) -> dict:
    n = len(rows)
    scored = [r for r in rows if not r.get("api_error")]
    refs = sum(r["object_reference_count"] for r in scored)
    values = {"total_tasks": n, "scored_tasks": len(scored), "api_errors": n - len(scored),
            **{k: sum(bool(r.get(k)) for r in rows) / n if n else None for k in ["task_planning_success", "action_validity", "format_compliance"]},
            "object_hallucination_rate": sum(r["hallucinated_references"] for r in scored) / refs if refs else None,
            "object_reference_count": refs,
            "hallucination_task_rate": sum(r["hallucination"] for r in scored) / len(scored) if scored else None,
            "parse_coverage": sum(not r["parsed_output"]["errors"] for r in scored) / len(scored) if scored else None,
            "failure_counts": dict(Counter(f for r in rows for f in r["failure_type"]))}
    values["planning_accuracy"] = values["task_planning_success"]
    values["hallucination_rate"] = values["object_hallucination_rate"]
    return values


def summarize(rows: list) -> dict:
    categories = ["single_step", "spatial", "multi_step", "impossible"]
    modes = ["free_form", "structured"]
    by_mode = {mode: {"overall": metrics([r for r in rows if r.get("prompt_mode", r.get("method")) == mode]),
                      "by_category": {c: metrics([r for r in rows if r.get("prompt_mode", r.get("method")) == mode and r["category"] == c]) for c in categories}}
               for mode in modes}
    return {"overall": metrics(rows),
            "by_category": {c: metrics([r for r in rows if r["category"] == c]) for c in categories},
            "by_prompt_mode": by_mode}
