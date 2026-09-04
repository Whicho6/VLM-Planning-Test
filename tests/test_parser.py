import pytest
from src.parser import parse_structured, parse_free_form


@pytest.mark.parametrize('text,error', [('PICK(apple)\nPLACE_IN(apple, box)', None), ('INVALID_TASK', None), ('FLY(apple)', 'illegal_action'), ('PICK(apple, box)', 'wrong_arity'), ('PICK apple', 'format_error'), ('', 'empty_output'), ('INVALID_TASK\nPICK(apple)', 'mixed_rejection'), ('PICK(Apple)', 'invalid_argument'), ('INVALID_TASK()', 'wrong_arity')])
def test_structured(text, error):
    errors = parse_structured(text)['errors']
    assert (error in errors) if error else not errors


def test_free_form_and_unsupported():
    assert not parse_free_form('First, pick up the apple; then place the apple inside the box.')['errors']
    assert parse_free_form('Do not put the apple inside the box.')['errors']
    assert parse_free_form('Put the apple inside the box. Dance.')['errors']
    assert len(parse_free_form('Put the apple inside the box.')['actions']) == 2


def test_rejection_cannot_hide_actions():
    assert parse_free_form('The task is impossible. Put the banana inside the box.')['errors']


def test_chinese_free_form():
    result = parse_free_form('先拿起纸巾，然后把纸巾放到鼠标的右边。')
    assert not result['errors']
    assert [a['action'] for a in result['actions']] == ['PICK', 'PLACE_RIGHT']
    assert parse_free_form('任务无法完成，因为场景中缺少计算器。')['actions'] == [{'action': 'INVALID_TASK', 'args': []}]
    assert parse_free_form('请随便处理一下纸巾。')['errors'] == ['unsupported_prose']


def test_free_form_final_plan_block_and_numbering():
    text = '''照片分析可以很详细，也可以使用 Markdown。
【最终操作计划】
1. 用机械夹爪抓取 **calculator**；
2. 将 calculator 放置在 umbrella 的右侧；
3. 拿起 pen。'''
    result = parse_free_form(text)
    assert not result['errors']
    assert result['actions'] == [
        {'action': 'PICK', 'args': ['calculator']},
        {'action': 'PLACE_RIGHT', 'args': ['calculator', 'umbrella']},
        {'action': 'PICK', 'args': ['pen']},
    ]


def test_public_object_aliases_are_normalized():
    result = parse_structured('PICK(tissue_box)')
    assert not result['errors']
    assert result['actions'][0]['args'] == ['tissue']
    assert result['normalizations'] == [{'from': 'tissue_box', 'to': 'tissue'}]
    assert parse_free_form('照片中没有鼠标，因此拒绝任务。')['actions'][0]['action'] == 'INVALID_TASK'
