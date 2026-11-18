import json
from types import SimpleNamespace

from rankai import llm


def test_claude_json_sends_the_schema_to_the_api_and_logs_the_cost(tmp_path, monkeypatch):
    sent = {}

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(stop_reason='end_turn', usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
                                   content=[SimpleNamespace(type='text', text='{"ok": true}')])

    fake = SimpleNamespace(messages=Messages(), with_options=lambda **kw: fake)
    monkeypatch.setattr(llm, '_client', fake)
    monkeypatch.setattr(llm, 'LOG', tmp_path / 'calls.jsonl')
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}
    assert llm.claude_json('sys', 'hi', schema, purpose='t') == {'ok': True}
    assert sent['model'] == 'claude-haiku-5-5' and sent['output_config']['format']['schema'] == schema
    row = json.loads((tmp_path / 'calls.jsonl').read_text())
    assert row['model'] == 'haiku' and row['cost_usd'] == 0.0002 and llm.spent('t') == 0.0002


def test_key_file_is_read_when_the_environment_has_no_key(tmp_path, monkeypatch):
    f = tmp_path / 'env'
    fake = 'sk-' + 'ant-test'  # built at runtime so secret scanners do not flag a fake key
    f.write_text(f'OTHER_SETTING=x\nexport CLAUDE_API_KEY="{fake}"\n')
    monkeypatch.setenv('ANTHROPIC_API_KEY', '')  # restored after the test
    monkeypatch.setattr(llm, 'KEY_FILE', f)
    monkeypatch.setattr(llm, '_client', None)
    assert llm.client().api_key == fake
    monkeypatch.setattr(llm, '_client', None)
