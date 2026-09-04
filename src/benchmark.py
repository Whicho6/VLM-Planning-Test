"""确定性生成与校验；真实照片必须由用户另行提供。"""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from PIL import Image
from src.utils import ROOT, read_json
from src.parser import parse_structured
from src.evaluator import simulate

CATEGORIES = ["single_step", "spatial", "multi_step", "impossible"]
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


def visual_instruction(category, objects, requested):
    if category in ["single_step", "impossible"]:
        name = NAMES[requested[0]["object"]]
        return f"如果照片中有{name}，就拿起它；如果没有，就拒绝任务。"
    if category == "spatial":
        return "把最右边的物体放到最左边物体的左边。"
    return "先把从左数第二个物体放到最右边物体的右边，然后拿起最左边的物体。"


def actions_for(goals):
    lines = []
    for g in goals:
        lines.append(f"PICK({g['object']})")
        if g["relation"] != "held":
            lines.append(f"PLACE_{g['relation'].upper()}({g['object']}, {g['target']})")
    return lines


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
        a, b, c, d = objects[:4]
        offset = (i + 3) % len(VOCABULARY)
        absent = next(x for x in VOCABULARY[offset:] + VOCABULARY[:offset] if x not in objects)
        specifications = [[goal(a, "held")], [goal(objects[-1], "left", a)],
                          [goal(b, "right", objects[-1]), goal(a, "held")], [goal(absent, "held")]]
        for category, requested in zip(CATEGORIES, specifications):
            impossible = category == "impossible"
            tasks.append({"id": f"task_{len(tasks)+1:03d}", "scene_id": sid, "image": scene["image"],
                          "objects": objects, "instruction": visual_instruction(category, objects, requested), "category": category,
                          "requested_goals": requested, "ground_truth": ["INVALID_TASK"] if impossible else actions_for(requested),
                          "target_state": [] if impossible else requested, "requires_rejection": impossible,
                          "missing_objects": [absent] if impossible else [], "visual_reference": True,
                          "benchmark_version": "2.1-visual-grounded"})
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
    paired = [t for t in tasks if t['category'] in ['spatial', 'multi_step']]
    check(any(len({str(t['ground_truth']) for t in paired if t['instruction'] == instruction}) > 1
              for instruction in {t['instruction'] for t in paired}), "视觉指代任务没有形成相同指令、不同答案的对照")
    lookup = {s['id']: s for s in scenes}
    for s in scenes:
        check(Counter(t['category'] for t in tasks if t['scene_id'] == s['id']) == Counter(CATEGORIES), f"{s['id']}：四类任务不完整")
        check(len(s['objects']) >= 4 and len(set(s['objects'])) == len(s['objects']) and set(s['objects']) <= set(VOCABULARY), f"{s['id']}：物体清单无效")
        check(not s['containers'], f"{s['id']}：不应声明容器")
        for r in s['relations']:
            check(r['object'] in s['objects'] and r['target'] in s['objects'] and r['object'] != r['target'] and r['relation'] in ['left', 'right'], f"{s['id']}：初始关系无效")
        relation_pairs = {(r['object'], r['target'], r['relation']) for r in s['relations']}
        check(not any((b, a, rel) in relation_pairs for a, b, rel in relation_pairs), f"{s['id']}：初始关系互相矛盾")
    for t in tasks:
        s = lookup.get(t['scene_id'])
        if not s:
            errors.append(f"{t['id']}：未知场景")
            continue
        prefix = t['id'] + "："
        check(t['image'] == s['image'] and t['objects'] == s['objects'], prefix + "场景信息不一致")
        check(t['instruction'] == visual_instruction(t['category'], s['objects'], t['requested_goals']), prefix + "指令与目标不一致")
        check(t.get('visual_reference') is True and t.get('benchmark_version') == '2.1-visual-grounded', prefix + "缺少视觉任务版本标记")
        refs = [x for g in t['requested_goals'] for x in [g['object'], g['target']] if x is not None]
        missing = set(refs) - set(s['objects'])
        impossible = t['category'] == 'impossible'
        check(bool(missing) == impossible, prefix + "物体存在性约束错误")
        check(set(t['missing_objects']) == missing and t['requires_rejection'] == impossible, prefix + "拒绝元数据错误")
        check(t['target_state'] == ([] if impossible else t['requested_goals']), prefix + "目标状态错误")
        check(t['ground_truth'] == (["INVALID_TASK"] if impossible else actions_for(t['requested_goals'])), prefix + "标准动作错误")
        check(len(t['requested_goals']) == (2 if t['category'] == 'multi_step' else 1), prefix + "目标数量错误")
        check(all(g['relation'] == 'held' and g['target'] is None for g in t['requested_goals']) if t['category'] == 'single_step' else True, prefix + "单步任务应为抓取")
        check(all(g['relation'] in ['left', 'right'] for g in t['requested_goals']) if t['category'] == 'spatial' else True, prefix + "空间关系错误")
        check(any(g['relation'] in ['left', 'right'] for g in t['requested_goals']) and any(g['relation'] == 'held' for g in t['requested_goals']) if t['category'] == 'multi_step' else True, prefix + "多步任务应同时包含放置和抓取目标")
        check(all(g['relation'] == 'held' for g in t['requested_goals']) if t['category'] == 'impossible' else True, prefix + "不可执行任务目标错误")
        if t['category'] == 'multi_step':
            pairs = {(g['object'], g['target'], g['relation']) for g in t['requested_goals']}
            contradictions = any((target, obj, relation) in pairs for obj, target, relation in pairs)
            check(not contradictions, prefix + "多步目标相互矛盾")
        parsed = parse_structured('\n'.join(t['ground_truth']))
        sim = simulate(parsed['actions'], s)
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
