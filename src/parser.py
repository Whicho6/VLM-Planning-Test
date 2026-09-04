"""Conservative, fully inspectable parsing; unsupported prose is never ignored."""
import re

ARITY = {"PICK": 1, "PLACE_IN": 2, "PLACE_LEFT": 2, "PLACE_RIGHT": 2, "INVALID_TASK": 0}
ALIASES = {"tissues": "tissue", "tissue_box": "tissue", "tissue_pack": "tissue",
           "drink_bottle": "bottle", "beverage_bottle": "bottle", "rubber": "eraser"}


def normalize_object(value):
    return ALIASES.get(value, value)


def parse_structured(text: str) -> dict:
    actions, errors, normalizations = [], [], []
    lines = text.strip().splitlines()
    if not lines:
        errors.append("empty_output")
    for line in lines:
        line = line.strip()
        if line == "INVALID_TASK":
            actions.append({"action": line, "args": []})
            continue
        match = re.fullmatch(r"([A-Z_]+)\(([^()]*)\)", line)
        if not match:
            errors.append("format_error")
            continue
        name, body = match.groups()
        raw_args = [a.strip() for a in body.split(",")] if body else []
        args = [normalize_object(a) for a in raw_args]
        normalizations.extend({"from": old, "to": new} for old, new in zip(raw_args, args) if old != new)
        actions.append({"action": name, "args": args})
        if name not in ARITY:
            errors.append("illegal_action")
        elif name == "INVALID_TASK" or len(args) != ARITY[name]:
            errors.append("wrong_arity")
        if any(not re.fullmatch(r"[a-z][a-z_0-9]*", a) for a in args):
            errors.append("invalid_argument")
    if any(a["action"] == "INVALID_TASK" for a in actions) and len(actions) != 1:
        errors.append("mixed_rejection")
    return {"actions": actions, "errors": errors, "unparsed": [], "normalizations": normalizations}


def parse_free_form(text: str) -> dict:
    strict = parse_structured(text)
    if not strict["errors"]:
        return strict
    marker = "【最终操作计划】"
    source = text.split(marker, 1)[1].strip() if marker in text else text.strip()
    if re.fullmatch(r"(?:The task is impossible|I cannot complete this task)(?: because the [a-z_]+ is (?:missing|absent|not present)(?: in the scene)?)?[.!]?", source, re.I):
        return {"actions": [{"action": "INVALID_TASK", "args": []}], "errors": [], "unparsed": [], "normalizations": []}
    chinese_reject = r"(?:(?:照片|图片|场景)中没有[^。；]+[，,]?(?:因此|所以)?拒绝任务|(?:任务无法完成|这个任务无法完成|无法完成(?:这个|该)?任务)(?:，?因为(?:场景中)?(?:没有|缺少)[^。]+)?)。?"
    if re.fullmatch(chinese_reject, source):
        return {"actions": [{"action": "INVALID_TASK", "args": []}], "errors": [], "unparsed": [], "normalizations": []}
    names = {"纸巾": "tissue", "鼠标": "mouse", "笔": "pen", "橡皮": "eraser",
             "眼镜": "glasses", "饮料瓶": "bottle", "瓶子": "bottle", "雨伞": "umbrella", "计算器": "calculator"}
    object_pattern = "纸巾|鼠标|笔|橡皮|眼镜|饮料瓶|瓶子|雨伞|计算器"
    # 新版提示要求把最终答案放在明确区块内；区块前的看图分析不参与动作解析。
    source = re.sub(r"\*\*|__|`|✅|✔", "", source)
    chinese_actions, normalizations = [], []
    chinese_ok = True
    clauses = [c.strip() for c in re.split(r"，?然后|；|。|\n", source) if c.strip()]
    if clauses and any(re.search(r"[\u4e00-\u9fff]", c) for c in clauses):
        for clause in clauses:
            clause = re.sub(r"^\s*(?:[-*]\s*|\d+[.、)]\s*)?(?:第一步[:：]?|第二步[:：]?|第三步[:：]?|首先|接着|最后|先|再|然后)?[，、 ]*", "", clause)
            pick = re.fullmatch(rf"(?:用机械夹爪)?(?:抓取|拿起|拿住)\s*(?:这个|那个|该)?({object_pattern}|[a-z_]+)(?:（[^）]*）|\([^)]*\))?", clause)
            place_in = None
            place_side = re.fullmatch(rf"(?:把|将)\s*({object_pattern}|[a-z_]+)(?:（[^）]*）|\([^)]*\))?\s*(?:放到|放置在)\s*({object_pattern}|[a-z_]+)(?:（[^）]*）|\([^)]*\))?\s*的?\s*(左边|右边|左侧|右侧)", clause)
            if pick:
                raw_obj = names.get(pick[1], pick[1])
                obj = normalize_object(raw_obj)
                if obj != raw_obj:
                    normalizations.append({"from": raw_obj, "to": obj})
                chinese_actions.append({"action": "PICK", "args": [obj]})
            elif place_in:
                obj, target = names[place_in[1]], names[place_in[2]]
                if not chinese_actions or chinese_actions[-1] != {"action": "PICK", "args": [obj]}:
                    chinese_actions.append({"action": "PICK", "args": [obj]})
                chinese_actions.append({"action": "PLACE_IN", "args": [obj, target]})
            elif place_side:
                raw_obj, raw_target = names.get(place_side[1], place_side[1]), names.get(place_side[2], place_side[2])
                obj, target = normalize_object(raw_obj), normalize_object(raw_target)
                normalizations.extend({"from": old, "to": new} for old, new in [(raw_obj, obj), (raw_target, target)] if old != new)
                if not chinese_actions or chinese_actions[-1] != {"action": "PICK", "args": [obj]}:
                    chinese_actions.append({"action": "PICK", "args": [obj]})
                action = "PLACE_LEFT" if place_side[3] in ["左边", "左侧"] else "PLACE_RIGHT"
                chinese_actions.append({"action": action, "args": [obj, target]})
            else:
                chinese_ok = False
        if chinese_ok and chinese_actions:
            return {"actions": chinese_actions, "errors": [], "unparsed": [], "normalizations": normalizations}
    actions, unparsed = [], []
    for clause in re.split(r"[.;\n]+|\bthen\b|\band\b", text, flags=re.I):
        clause = re.sub(r"^\s*(?:\d+[.)]?\s*|[-*]\s*|first[, :]*)", "", clause, flags=re.I).strip(" ,")
        if not clause:
            continue
        clause = clause.lower()
        pick = re.fullmatch(r"(?:pick up|pick|grasp) (?:the )?([a-z_]+)", clause)
        place = re.fullmatch(r"(put|place|move) (?:the )?([a-z_]+) (in|inside|into|to the left of|to the right of|left of|right of) (?:the )?([a-z_]+)", clause)
        if pick:
            obj = normalize_object(pick[1])
            if obj != pick[1]:
                normalizations.append({"from": pick[1], "to": obj})
            actions.append({"action": "PICK", "args": [obj]})
        elif place:
            verb, obj, relation, target = place.groups()
            raw_obj, raw_target = obj, target
            obj, target = normalize_object(obj), normalize_object(target)
            normalizations.extend({"from": old, "to": new} for old, new in [(raw_obj, obj), (raw_target, target)] if old != new)
            # 'move/put/place' denotes a full transfer if no explicit grasp precedes it.
            if not actions or actions[-1] != {"action": "PICK", "args": [obj]}:
                actions.append({"action": "PICK", "args": [obj]})
            name = "PLACE_LEFT" if "left" in relation else "PLACE_RIGHT" if "right" in relation else "PLACE_IN"
            actions.append({"action": name, "args": [obj, target]})
        else:
            unparsed.append(clause)
    return {"actions": actions, "errors": ["unsupported_prose"] if unparsed or not actions else [], "unparsed": unparsed, "normalizations": normalizations}
