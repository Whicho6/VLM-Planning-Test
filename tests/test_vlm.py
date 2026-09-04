import json
from unittest.mock import patch
from src.vlm import CompatibleVLM


def test_real_adapter_request_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv('VLM_API_KEY', 'unit-test-key-not-real')
    monkeypatch.setenv('VLM_MODEL', 'unit-test-model-not-real')
    monkeypatch.setenv('VLM_BASE_URL', 'https://example.org/v1')
    photo = tmp_path / 'image.jpg'
    photo.write_bytes(b'test-image-bytes')
    captured = []
    class Response:
        headers = {'x-request-id': 'header-request-id'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({'id': 'body-request-id', 'usage': {'prompt_tokens': 4, 'completion_tokens': 1, 'total_tokens': 5}, 'choices': [{'finish_reason': 'stop', 'message': {'content': 'INVALID_TASK'}}]}).encode()
    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data))
        return Response()
    with patch('urllib.request.urlopen', fake_urlopen):
        client = CompatibleVLM()
        for mode in ['free_form', 'structured']:
            assert client.plan(photo, 'Move the apple.', mode) == 'INVALID_TASK'
    assert captured[0]['model'] == captured[1]['model']
    assert captured[0]['messages'][1] == captured[1]['messages'][1]
    assert captured[0]['messages'][0] != captured[1]['messages'][0]
    assert 'ground_truth' not in json.dumps(captured)
    assert client.last_usage['total_tokens'] == 5
    assert client.last_request_id == 'body-request-id'


def test_real_adapter_can_send_text_only(tmp_path, monkeypatch):
    monkeypatch.setenv('VLM_API_KEY', 'unit-test-key-not-real')
    monkeypatch.setenv('VLM_MODEL', 'unit-test-model-not-real')
    monkeypatch.setenv('VLM_BASE_URL', 'https://example.org/v1')
    captured = []
    class Response:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': 'INVALID_TASK'}}]}).encode()
    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data)); return Response()
    with patch('urllib.request.urlopen', fake_urlopen):
        CompatibleVLM().plan(None, '测试指令', 'structured')
    assert captured[0]['messages'][1]['content'] == [{'type': 'text', 'text': '测试指令'}]
