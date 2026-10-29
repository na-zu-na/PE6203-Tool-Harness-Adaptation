"""Stage-one boundaries: no label leakage, useful failure logs, portable Agent import."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def test_select_task_does_not_expose_reference_answer():
    # A runner passing the source answer/trajectory to the model would invalidate evaluation.
    from member1.run_task import load_task

    task = load_task(156)
    assert task['idx'] == 156
    assert task['question'] == 'What is the total number of seconds that have passed since the start of the day in Tokyo right now?'
    assert task['servers'] == {
        '@guanxiong/mcp-server-time': ['get_current_time', 'get_time_info'],
        'calculator': ['calculate'],
    }
    assert set(task) == {'idx', 'question', 'servers', 'tool_calls'}


def test_missing_key_produces_configuration_error_log(tmp_path):
    # A missing credential must not be mistaken for an empty successful benchmark answer.
    output = tmp_path / 'run'
    env = {k: v for k, v in os.environ.items() if k != 'ARK_API_KEY'}
    result = subprocess.run([
        sys.executable, '-X', 'utf8', 'member1/run_task.py', '--env-file', str(tmp_path / 'absent.env'),
        '--output-dir', str(output),
    ], cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode != 0
    summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert summary['status'] == 'configuration_error'
    assert summary['task_id'] == 156
    assert 'ARK_API_KEY' in summary['error']
    assert not (output / 'ANSWER' / '156.json').exists()


def test_agent_can_load_without_gpu_or_fastchat():
    # Eager FastChat imports otherwise make a remote API run require torch on Windows.
    result = subprocess.run([
        sys.executable, '-X', 'utf8', '-c',
        "import sys; sys.path.insert(0, 'src'); from custom.agents.SimpleOpenAIAgent import ChatModel; "
        "assert not any(n == 'torch' or n.startswith('fastchat') for n in sys.modules)",
    ], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


def test_model_error_is_reported_to_log_callback():
    from custom.agents.SimpleOpenAIAgent import ChatModel

    events = []
    agent = ChatModel(model_name='test', api_key='test', event_callback=lambda kind, value: events.append((kind, value)))
    def unavailable(**kwargs):
        raise ConnectionError('model endpoint unavailable')
    agent.complete_with_retry = unavailable
    agent.run_with_server('test')
    assert ('model_error', {'error': 'model endpoint unavailable'}) in events


def test_raw_tool_result_is_preserved_in_log_callback(monkeypatch):
    from custom.agents import SimpleOpenAIAgent as module
    from openai.types.chat import ChatCompletionMessage
    from mcp.types import CallToolResult, TextContent

    events = []
    agent = module.ChatModel(model_name='test', api_key='test', tool_server_map={'calculate': 'calculator'},
                             event_callback=lambda kind, value: events.append((kind, value)))
    messages = iter([
        ChatCompletionMessage(role='assistant', content=None, tool_calls=[{
            'id': 'call1', 'type': 'function', 'function': {'name': 'calculate', 'arguments': '{"expression":"1+1"}'},
        }]),
        ChatCompletionMessage(role='assistant', content='[FINISH] 2'),
    ])
    agent.complete_with_retry = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=next(messages))])
    async def tool_response(*args):
        return CallToolResult(content=[TextContent(type='text', text='2' + 'x' * 900)])
    monkeypatch.setattr(module, 'call_tool_with_1mcp', tool_response)
    answer, trajectory, stopped, exceeded = agent.run_with_server('calculate')
    saved = [value for kind, value in events if kind == 'tool_result']
    assert saved[0]['result']['content'][0]['text'] == '2' + 'x' * 900
    assert saved[0]['name'] == 'calculate'
    assert stopped and answer == '[FINISH] 2'


def test_final_answer_after_tool_result_stops_without_forcing_another_call(monkeypatch):
    # The upstream retry prompt otherwise makes a completed task call the tools again forever.
    from custom.agents import SimpleOpenAIAgent as module
    from openai.types.chat import ChatCompletionMessage
    from mcp.types import CallToolResult, TextContent

    agent = module.ChatModel(model_name='test', api_key='test', tool_server_map={'calculate': 'calculator'},
                             stop_on_final_answer=True)
    messages = iter([
        ChatCompletionMessage(role='assistant', content=None, tool_calls=[{
            'id': 'call1', 'type': 'function', 'function': {'name': 'calculate', 'arguments': '{"expression":"1+1"}'},
        }]),
        ChatCompletionMessage(role='assistant', content='The result is 2.'),
    ])
    agent.complete_with_retry = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=next(messages))])
    async def tool_response(*args):
        return CallToolResult(content=[TextContent(type='text', text='2')])
    monkeypatch.setattr(module, 'call_tool_with_1mcp', tool_response)
    answer, trajectory, stopped, exceeded = agent.run_with_server('calculate')
    assert stopped and not exceeded
    assert answer == 'The result is 2.'
    assert [m['role'] for m in trajectory] == ['system', 'user', 'assistant', 'tool', 'assistant']
