"""Provider-neutral interface plus a Chat Completions-compatible HTTP adapter."""
import base64
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Protocol
from src.prompts import prompt_for
from src.utils import ROOT


class VLM(Protocol):
    def plan(self, image_path, instruction: str, mode: str = 'structured') -> str: ...


class MockVLM:
    """Oracle fixture for plumbing tests; does not see images or measure model ability."""
    model = 'MOCK_ORACLE_NOT_A_VLM'

    def __init__(self, tasks):
        self.tasks = tasks
        self.last_usage = None
        self.last_request_id = None

    def plan(self, image_path, instruction, mode='structured'):
        prompt_for(mode)
        task = next((t for t in self.tasks if image_path is not None and Path(t['image']).name == Path(image_path).name and t['instruction'] == instruction), None)
        if task is None:
            raise ValueError('Mock only supports benchmark image/instruction pairs; use --task-id.')
        if mode == 'structured':
            return '\n'.join(task['ground_truth'])
        if task['requires_rejection']:
            return "任务无法完成，因为场景中缺少指令要求的物体。"
        names = {"tissue": "纸巾", "mouse": "鼠标", "pen": "笔", "eraser": "橡皮",
                 "glasses": "眼镜", "bottle": "饮料瓶", "umbrella": "雨伞", "calculator": "计算器"}
        lines = []
        for action in task['ground_truth']:
            name, body = action.split('(', 1)
            args = [a.strip() for a in body[:-1].split(',')]
            if name == 'PICK':
                lines.append(f"拿起{names[args[0]]}")
            else:
                side = '左边' if name == 'PLACE_LEFT' else '右边'
                lines.append(f"把{names[args[0]]}放到{names[args[1]]}的{side}")
        return "，然后".join(lines) + "。"


class CompatibleVLM:
    def __init__(self):
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env')
        self.key = os.getenv('VLM_API_KEY', '')
        self.model = os.getenv('VLM_MODEL', '')
        self.base_url = os.getenv('VLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
        if not self.key or not self.model:
            raise ValueError('Set VLM_API_KEY and VLM_MODEL in .env or environment.')
        if not self.base_url.startswith('https://'):
            raise ValueError('VLM_BASE_URL must use HTTPS.')
        self.last_usage = None
        self.last_request_id = None

    def plan(self, image_path, instruction, mode='structured'):
        self.last_usage = None
        self.last_request_id = None
        user_content = [{'type': 'text', 'text': instruction}]
        if image_path is not None:
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode('ascii')
            user_content.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + encoded}})
        payload = {'model': self.model, 'temperature': 0, 'max_tokens': 512,
                   'messages': [{'role': 'system', 'content': prompt_for(mode)},
                                {'role': 'user', 'content': user_content}]}
        request = urllib.request.Request(self.base_url + '/chat/completions', data=json.dumps(payload).encode(),
                                         headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
                self.last_request_id = response.headers.get('x-request-id') if hasattr(response, 'headers') else None
            self.last_request_id = result.get('request_id') or result.get('id') or self.last_request_id
            self.last_usage = result.get('usage')
            choice = result['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise ValueError('incomplete_response')
            output = choice['message']['content']
            if not isinstance(output, str) or not output.strip():
                raise ValueError('empty_response')
            return output
        except urllib.error.HTTPError as exc:
            # Never persist server response bodies or request headers (may contain secrets).
            raise RuntimeError(f'HTTP {exc.code}') from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('network_error_or_timeout') from None
