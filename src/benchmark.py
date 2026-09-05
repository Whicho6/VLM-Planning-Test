"""确定性生成与校验；真实照片必须由用户另行提供。"""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from PIL import Image
from src.utils import ROOT, read_json
from src.parser import parse_structured
from src.evaluator import simulate

CATEGORIES = ["single_step", "spatial", "multi_step", "impossible"]
BENCHMARK_VERSION = "3.1-visual-counterfactual"
VOCABULARY = ["tissue", "mouse", "pen", "eraser", "glasses", "bottle", "umbrella", "calculator"]
NAMES = {"tissue": "纸巾", "mouse": "鼠标", "pen": "笔", "eraser": "橡皮",
         "glasses": "眼镜", "bottle": "饮料瓶", "umbrella": "雨伞", "calculator": "计算器"}
LAYOUTS = [
    ["tissue", "mouse", "pen", "eraser"],
    ["glasses", "bottle", "umbrella", "calculator"],
    ["mouse", "eraser", "glasses", "bottle"],
    ["pen", "calculator", "tissue", "umbrella"],
    ["bottle", "tissue", "mouse", "glasses"],
    ["umbrella", "pen", "eraser", "calculator"],
    ["calculator", "glasses", "bottle", "pen"],
    ["eraser", "umbrella", "tissue", "mouse"],
    ["tissue", "glasses", "calculator", "eraser"],
    ["mouse", "bottle", "pen", "umbrella"],
]

# 五组场景对。每组两张照片中 subject/object 的左右关系相反。
# 同一句指令因此必须选择不同的放置方向。
SPATIAL_PAIRS = {
    1: ("eraser", "tissue"), 8: ("eraser", "tissue"),
    2: ("calculator", "glasses"), 7: ("calculator", "glasses"),
    3: ("bottle", "glasses"), 5: ("bottle", "glasses"),
    4: ("calculator", "tissue"), 9: ("calculator", "tissue"),
    6: ("umbrella", "pen"), 10: ("umbrella", "pen"),
}

# Multi-step 使用另一组配对，避免与同场景 Spatial 任务近似重复。
MULTI_PAIRS = {
    1: ("pen", "tissue"), 4: ("pen", "tissue"),
    2: ("bottle", "glasses"), 5: ("bottle", "glasses"),
    3: ("eraser", "glasses"), 9: ("eraser", "glasses"),
    6: ("calculator", "pen"), 7: ("calculator", "pen"),
    8: ("mouse", "umbrella"), 10: ("mouse", "umbrella"),
}

# 每个 Single-step 的存在目标，都在另一个场景的 Impossible 任务中缺失。
IMPOSSIBLE_QUERY = {
    1: ("glasses", "existence_02"), 2: ("tissue", "existence_01"),
    3: ("tissue", "existence_09"), 4: ("mouse", "existence_03"),
    5: ("pen", "existence_04"), 6: ("bottle", "existence_05"),
    7: ("umbrella", "existence_06"), 8: ("calculator", "existence_07"),
    9: ("mouse", "existence_10"), 10: ("eraser", "existence_08"),
}


def goal(obj, relation, target=None):
    return {"object": obj, "relation": relation, "target": target}


def instruction_for(goals, variant=0):
    parts = []
    for g in goals:
        if g["relation"] == "held":
            parts.append(f"{'抓取' if variant else '拿起'}{NAMES[g['object']]}")
        else:
            side = "左边" if g["relation"] == "left" else "右边"
            parts.append(f"把{NAMES[g['object']]}放到{NAMES[g['target']]}的{side}")
    return "，然后".join(parts) + "。"


def spatial_instruction(subject, reference):
    s, r = NAMES[subject], NAMES[reference]
    return f"观察{s}和{r}当前的位置：如果{s}在{r}左边，就把{s}放到{r}右边；否则，把{s}放到{r}左边。"


def multi_step_instruction(subject, reference):
    s, r = NAMES[subject], NAMES[reference]
    return f"观察{s}和{r}当前的位置：如果{s}在{r}左边，先把{s}放到{r}右边，再拿起{r}；否则，先把{s}放到{r}左边，再拿起{r}。"


def visual_instruction(category, objects, requested, decision=None):
    if category in ["single_step", "impossible"]:
        name = NAMES[requested[0]["object"]]
        return f"如果照片中有{name}，就拿起它；如果没有，就拒绝任务。"
    if category == "spatial":
        return spatial_instruction(decision["subject"], decision["reference"])
    return multi_step_instruction(decision["subject"], decision["reference"])


def actions_for(goals):
    lines = []
    for g in goals:
        lines.append(f"PICK({g['object']})")
        if g["relation"] != "held":
            lines.append(f"PLACE_{g['relation'].upper()}({g['object']}, {g['target']})")
    return lines


def conditional_case(pair_map, scene_number, objects, multi_step=False):
    subject, reference = pair_map[scene_number]
    subject_is_left = objects.index(subject) < objects.index(reference)
    placement = "right" if subject_is_left else "left"
    decision = {
        "subject": subject, "relation": "left", "reference": reference,
        "observed": subject_is_left, "selected_branch": "if" if subject_is_left else "else",
        "moved_object": subject, "target_object": reference, "placement": placement,
    }
    goals = [goal(subject, placement, reference)]
    if multi_step:
        goals.append(goal(reference, "held"))
        decision["followup_object"] = reference
    return goals, decision


def generate() -> tuple[list[dict], list[dict]]:
    scenes, tasks = [], []
    for i, objects in enumerate(LAYOUTS, 1):
        sid = f"scene_{i:02d}"
        scene = {"id": sid, "image": f"data/images/{sid}.jpg", "annotation_status": "planned_placeholder",
                 "verified_image_sha256": None, "objects": objects, "containers": [],
                 "relations": [goal(objects[j], "left", objects[j + 1]) for j in range(len(objects) - 1)],
                 "initial_state": "All objects are separate on the tabletop; nothing is held.",
                 "left_to_right": objects}
        scenes.append(scene)
        present = objects[0]
        absent, impossible_pair_id = IMPOSSIBLE_QUERY[i]
        spatial_goals, spatial_decision = conditional_case(SPATIAL_PAIRS, i, objects)
        multi_goals, multi_decision = conditional_case(MULTI_PAIRS, i, objects, multi_step=True)
        specifications = [
            ("single_step", [goal(present, "held")],
             {"pair_id": f"existence_{i:02d}", "queried_object": present, "observed": True, "expected_action": "PICK"}),
            ("spatial", spatial_goals, spatial_decision),
            ("multi_step", multi_goals, multi_decision),
            ("impossible", [goal(absent, "held")],
             {"pair_id": impossible_pair_id, "queried_object": absent, "observed": False, "expected_action": "INVALID_TASK"}),
        ]
        for category, requested, decision in specifications:
            impossible = category == "impossible"
            instruction_decision = decision if category in {"spatial", "multi_step"} else None
            task = {"id": f"task_{len(tasks)+1:03d}", "scene_id": sid, "image": scene["image"],
                    "objects": objects, "instruction": visual_instruction(category, objects, requested, instruction_decision),
                    "category": category, "requested_goals": requested,
                    "ground_truth": ["INVALID_TASK"] if impossible else actions_for(requested),
                    "target_state": [] if impossible else requested, "requires_rejection": impossible,
                    "missing_objects": [absent] if impossible else [], "visual_reference": True,
                    "benchmark_version": BENCHMARK_VERSION}
            if category in {"single_step", "impossible"}:
                task["existence_decision"] = decision
            elif category == "spatial":
                task["spatial_decision"] = decision
            else:
                task["multi_step_decision"] = decision
            tasks.append(task)
    return scenes, tasks


def validate(scenes: list[dict], tasks: list[dict]) -> list[str]:
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)

    check(len(scenes) == 10 and len({s['id'] for s in scenes}) == 10, "应有 10 个不同场景")
    check(len(tasks) == 40 and len({t['id'] for t in tasks}) == 40, "应有 40 条不同任务")
    check(Counter(t['category'] for t in tasks) == Counter({c: 10 for c in CATEGORIES}), "类别数量不平衡")
    check(len({(t['scene_id'], str(t['requested_goals'])) for t in tasks}) == 40, "同一场景存在重复语义任务")

    # Single-step/Impossible：同一存在性问题必须各有一张“存在”和“不存在”的图片。
    existence_tasks = [t for t in tasks if t['category'] in {'single_step', 'impossible'}]
    existence_pairs = {}
    for t in existence_tasks:
        pair_id = (t.get('existence_decision') or {}).get('pair_id')
        existence_pairs.setdefault(pair_id, []).append(t)
    check(None not in existence_pairs and len(existence_pairs) == 10
          and all(len(group) == 2 for group in existence_pairs.values()),
          "存在性任务应组成 10 组图像反事实对")
    for pair_id, group in existence_pairs.items():
        check(len({t['instruction'] for t in group}) == 1, f"{pair_id}：存在性场景对指令不同")
        check({t['category'] for t in group} == {'single_step', 'impossible'}, f"{pair_id}：应包含可执行和不可执行任务")
        check({t.get('existence_decision', {}).get('observed') for t in group} == {True, False}, f"{pair_id}：没有形成存在/缺失对照")
        check(len({tuple(t['ground_truth']) for t in group}) == 2, f"{pair_id}：答案没有随图片变化")

    # Spatial/Multi-step：同一句条件指令在两张图中必须触发相反分支。
    for category, field in [('spatial', 'spatial_decision'), ('multi_step', 'multi_step_decision')]:
        selected = [t for t in tasks if t['category'] == category]
        groups = {text: [t for t in selected if t['instruction'] == text]
                  for text in {t['instruction'] for t in selected}}
        check(len(groups) == 5 and all(len(group) == 2 for group in groups.values()),
              f"{category} 任务应组成 5 组相同指令的场景对")
        for text, group in groups.items():
            check({t.get(field, {}).get('observed') for t in group} == {True, False},
                  f"{category} 场景对没有触发相反条件分支：{text}")
            check({t.get(field, {}).get('placement') for t in group} == {'left', 'right'},
                  f"{category} 场景对没有选择相反方向：{text}")
            check(len({tuple(t['ground_truth']) for t in group}) == 2,
                  f"{category} 标准动作没有随图片变化：{text}")

    lookup = {s['id']: s for s in scenes}
    for scene in scenes:
        check(Counter(t['category'] for t in tasks if t['scene_id'] == scene['id']) == Counter(CATEGORIES), f"{scene['id']}：四类任务不完整")
        check(len(scene['objects']) >= 4 and len(set(scene['objects'])) == len(scene['objects']) and set(scene['objects']) <= set(VOCABULARY), f"{scene['id']}：物体清单无效")
        check(scene.get('left_to_right') == scene['objects'], f"{scene['id']}：从左到右标注与物体清单不一致")
        check(not scene['containers'], f"{scene['id']}：不应声明容器")
        for relation in scene['relations']:
            check(relation['object'] in scene['objects'] and relation['target'] in scene['objects']
                  and relation['object'] != relation['target'] and relation['relation'] in ['left', 'right'],
                  f"{scene['id']}：初始关系无效")
        relation_pairs = {(r['object'], r['target'], r['relation']) for r in scene['relations']}
        check(not any((b, a, rel) in relation_pairs for a, b, rel in relation_pairs), f"{scene['id']}：初始关系互相矛盾")

    for task in tasks:
        scene = lookup.get(task['scene_id'])
        if not scene:
            errors.append(f"{task['id']}：未知场景")
            continue
        prefix = task['id'] + "："
        check(task['image'] == scene['image'] and task['objects'] == scene['objects'], prefix + "场景信息不一致")
        check(task.get('visual_reference') is True and task.get('benchmark_version') == BENCHMARK_VERSION, prefix + "缺少当前视觉任务版本标记")
        refs = [x for g in task['requested_goals'] for x in [g['object'], g['target']] if x is not None]
        missing = set(refs) - set(scene['objects'])
        impossible = task['category'] == 'impossible'
        check(bool(missing) == impossible, prefix + "物体存在性约束错误")
        check(set(task['missing_objects']) == missing and task['requires_rejection'] == impossible, prefix + "拒绝元数据错误")
        check(task['target_state'] == ([] if impossible else task['requested_goals']), prefix + "目标状态错误")
        check(task['ground_truth'] == (["INVALID_TASK"] if impossible else actions_for(task['requested_goals'])), prefix + "标准动作错误")
        check(len(task['requested_goals']) == (2 if task['category'] == 'multi_step' else 1), prefix + "目标数量错误")
        check(all(g['relation'] == 'held' and g['target'] is None for g in task['requested_goals']) if task['category'] == 'single_step' else True, prefix + "单步任务应为抓取")
        check(all(g['relation'] in ['left', 'right'] for g in task['requested_goals']) if task['category'] == 'spatial' else True, prefix + "空间关系错误")
        check(any(g['relation'] in ['left', 'right'] for g in task['requested_goals']) and any(g['relation'] == 'held' for g in task['requested_goals']) if task['category'] == 'multi_step' else True, prefix + "多步任务应同时包含放置和抓取目标")
        check(all(g['relation'] == 'held' for g in task['requested_goals']) if impossible else True, prefix + "不可执行任务目标错误")

        if task['category'] in {'single_step', 'impossible'}:
            d = task.get('existence_decision') or {}
            required = {'pair_id', 'queried_object', 'observed', 'expected_action'}
            check(required <= set(d), prefix + "缺少存在性决策元数据")
            if required <= set(d):
                observed = d['queried_object'] in scene['objects']
                check(d['observed'] == observed, prefix + "物体存在性与场景不一致")
                check(d['expected_action'] == ('PICK' if observed else 'INVALID_TASK'), prefix + "存在性动作决策错误")
                check(task['instruction'] == visual_instruction(task['category'], scene['objects'], task['requested_goals']), prefix + "存在性指令错误")
            check('spatial_decision' not in task and 'multi_step_decision' not in task, prefix + "存在性任务包含多余决策元数据")
        else:
            field = 'spatial_decision' if task['category'] == 'spatial' else 'multi_step_decision'
            d = task.get(field) or {}
            required = {'subject', 'relation', 'reference', 'observed', 'selected_branch', 'moved_object', 'target_object', 'placement'}
            check(required <= set(d), prefix + "缺少条件空间决策元数据")
            if required <= set(d):
                observed = scene['left_to_right'].index(d['subject']) < scene['left_to_right'].index(d['reference'])
                placement = 'right' if observed else 'left'
                expected_goals = [goal(d['subject'], placement, d['reference'])]
                if task['category'] == 'multi_step':
                    expected_goals.append(goal(d['reference'], 'held'))
                    check(d.get('followup_object') == d['reference'], prefix + "多步后续抓取对象错误")
                check(d['relation'] == 'left' and d['observed'] == observed, prefix + "空间条件与场景不一致")
                check(d['selected_branch'] == ('if' if observed else 'else'), prefix + "条件分支错误")
                check(d['moved_object'] == d['subject'] and d['target_object'] == d['reference'] and d['placement'] == placement, prefix + "空间动作决策错误")
                check(task['requested_goals'] == expected_goals, prefix + "目标与条件决策不一致")
                check(task['instruction'] == visual_instruction(task['category'], scene['objects'], task['requested_goals'], d), prefix + "条件指令错误")
            check('existence_decision' not in task, prefix + "条件任务包含存在性决策元数据")

        parsed = parse_structured('\n'.join(task['ground_truth']))
        sim = simulate(parsed['actions'], scene)
        check(not parsed['errors'] and not sim['invalid'], prefix + "标准动作无法执行")
    return errors


def image_issues(scenes: list[dict], require_verified: bool = False, root: Path = ROOT) -> list[str]:
    issues = []
    for scene in scenes:
        path = root / scene['image']
        if not path.is_file():
            issues.append(f"{scene['id']}：缺少图片：{scene['image']}")
            continue
        try:
            with Image.open(path) as img:
                img.verify()
        except (OSError, ValueError):
            issues.append(f"{scene['id']}：图片无效或损坏")
            continue
        if require_verified and (scene['annotation_status'] != 'verified_real' or scene['verified_image_sha256'] != sha256(path.read_bytes()).hexdigest()):
            issues.append(f"{scene['id']}：照片尚未核对，或核对后发生了变化")
    return issues


def load_benchmark():
    return read_json(ROOT / 'data/scenes.json'), read_json(ROOT / 'data/tasks.json')