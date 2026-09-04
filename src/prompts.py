COMMON = '''请根据图片和中文指令规划桌面物体操作。动作中的物体名称必须使用英文标识。
画面中每类物体只有一个。左右方向以观看图片的人的视角为准。
机械夹爪一次只能拿一个物体，放置前必须先抓取。当前场景没有可用容器。
物体可以被拿起，或放到另一物体左边/右边；不具备其他技能。
必须遵守指令明确要求的顺序。如果缺少任何必需物体，应拒绝整个任务。
不能仅因指令提到某个物体就假设它存在。'''
FREE_FORM = COMMON + '''\n可以先用自然中文简要分析图片。最后必须另起一段，以【最终操作计划】开头。
该段只能逐句使用“拿起物体”或“把物体放到另一物体的左边/右边”；物体可用中文名或小写英文标识，不要在该段添加解释。
无法完成时，最终一行只写“任务无法完成，因为场景中缺少所需物体。”'''
STRUCTURED = COMMON + '''\n只能逐行输出下列格式之一：
PICK(object)
PLACE_IN(object, container)
PLACE_LEFT(object, target)
PLACE_RIGHT(object, target)
无法完成时只输出一行 INVALID_TASK。
物体标识使用小写英文。禁止添加解释、编号、代码块或额外动作。'''
STRUCTURED += '''\n每个 PLACE_LEFT、PLACE_RIGHT 或 PLACE_IN 前都必须先输出对应物体的 PICK，即使中文指令只写“把”。
多步格式示例：
PICK(mouse)
PLACE_RIGHT(mouse, eraser)
PICK(tissue)'''


def prompt_for(mode):
    if mode not in ['structured', 'free_form']:
        raise ValueError('Unknown mode')
    return STRUCTURED if mode == 'structured' else FREE_FORM
