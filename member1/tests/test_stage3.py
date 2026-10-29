import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def packet(strategy='no_update'):
    return {'schema_version': 1, 'task_id': 156, 'strategy': strategy, 'source_version': 'Early',
        'instructions': 'Use the supplied old usage rule verbatim.', 'tools': [{
            'name': 'clock__old_time', 'source_server': '@guanxiong/mcp-server-time',
            'source_name': 'old_time', 'description': 'Old description that must not refresh.',
            'inputSchema': {'type': 'object', 'properties': {'old_zone': {'type': 'string'}}},
        }]}


@pytest.mark.parametrize('strategy', ['no_update', 'full_rewrite', 'selective_patch'])
def test_external_knowledge_preserves_old_schema_and_routing(tmp_path, strategy):
    from member1.knowledge import load_knowledge
    supplied = packet(strategy)
    path = tmp_path / '156.json'
    raw = json.dumps(supplied, ensure_ascii=False).encode('utf-8')
    path.write_bytes(raw)
    loaded = load_knowledge(path, 156)
    assert loaded['tools'] == supplied['tools']
    assert loaded['routes'] == {'clock__old_time': 'clock_1mcp_old_time'}
    assert loaded['instructions'] == supplied['instructions']
    assert loaded['packet']['strategy'] == strategy
    assert loaded['raw_bytes'] == raw
    assert loaded['update_cost'] is None


@pytest.mark.parametrize('fault', ['wrong_task', 'duplicate', 'bad_schema', 'negative_cost', 'other_server'])
def test_bad_knowledge_is_rejected_before_model_requests(tmp_path, fault):
    from member1.knowledge import load_knowledge
    supplied = packet()
    if fault == 'wrong_task': supplied['task_id'] = 28
    if fault == 'duplicate': supplied['tools'].append(copy.deepcopy(supplied['tools'][0]))
    if fault == 'bad_schema': supplied['tools'][0]['inputSchema'] = {'type': 'invalid-type'}
    if fault == 'negative_cost': supplied['update_cost'] = {'tokens': -3}
    if fault == 'other_server': supplied['tools'][0]['source_server'] = 'mcp-filesystem-server'
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(supplied), encoding='utf-8')
    with pytest.raises(ValueError):
        load_knowledge(path, 156)


def test_member2_can_export_a_real_saved_catalog(tmp_path):
    from member1.knowledge import export_knowledge, load_knowledge
    tools = ROOT / 'member1/evidence/stage2/validation/Early-task-156/result/tools.json'
    target = tmp_path / '156.json'
    export_knowledge(tools, target, 156, 'Early', 'no_update')
    loaded = load_knowledge(target, 156)
    assert loaded['tools'] == json.loads(tools.read_text(encoding='utf-8'))
    assert all('convert_timezone' not in t['name'] for t in loaded['tools'])


def test_file_mode_does_not_refresh_from_the_live_server(tmp_path, monkeypatch):
    from member1 import run_task
    from mcp.types import ListToolsResult, Tool
    supplied = packet()
    supplied['update_cost'] = {'tokens': 123, 'seconds': 1.25}
    path = tmp_path / '156.json'
    path.write_bytes(json.dumps(supplied).encode())
    async def audit_only(url):
        return ListToolsResult(tools=[Tool(name='clock_1mcp_new_time', description='NEW server description',
            inputSchema={'type': 'object', 'properties': {'new_zone': {'type': 'string'}}})])
    monkeypatch.setattr(run_task, 'discover_tools', audit_only)
    out = tmp_path / 'result'
    monkeypatch.setattr(sys, 'argv', ['run_task.py', '--knowledge-file', str(path), '--task-id', '156',
        '--output-dir', str(out), '--check-tools'])
    assert run_task.main() == 0
    assert (out / 'knowledge.json').read_bytes() == path.read_bytes()
    assert json.loads((out / 'tools.json').read_text(encoding='utf-8')) == supplied['tools']
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    assert summary['strategy'] == 'no_update'
    assert summary['knowledge_mode'] == 'provided_file'
    assert summary['update_cost'] == {'tokens': 123, 'seconds': 1.25}


def test_tool_event_checkpoint_includes_the_returned_tool_message(monkeypatch):
    from custom.agents import SimpleOpenAIAgent as module
    from openai.types.chat import ChatCompletionMessage
    from mcp.types import CallToolResult, TextContent
    checkpoints = []
    agent = module.ChatModel(model_name='test', api_key='test', tool_server_map={'calculate': 'calculator'},
        stop_on_final_answer=True, event_callback=lambda kind, value:
        checkpoints.append(copy.deepcopy(agent.messages)) if kind == 'tool_result' else None)
    messages = iter([
        ChatCompletionMessage(role='assistant', content=None, tool_calls=[{'id': 'a', 'type': 'function',
            'function': {'name': 'calculate', 'arguments': '{"expression":"1+1"}'}}]),
        ChatCompletionMessage(role='assistant', content='done'),
    ])
    agent.complete_with_retry = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=next(messages))])
    async def returned(*args): return CallToolResult(content=[TextContent(type='text', text='2')])
    monkeypatch.setattr(module, 'call_tool_with_1mcp', returned)
    agent.run_with_server('task')
    assert checkpoints[0][-1]['role'] == 'tool'
    assert checkpoints[0][-1]['tool_call_id'] == 'a'


def test_tool_timeout_keeps_the_matching_call_id(monkeypatch):
    import asyncio
    from custom.agents import SimpleOpenAIAgent as module
    from openai.types.chat import ChatCompletionMessage
    agent = module.ChatModel(model_name='test', api_key='test', max_round=1,
        tool_server_map={'calculate': 'calculator'})
    agent.complete_with_retry = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
        message=ChatCompletionMessage(role='assistant', content=None, tool_calls=[{
            'id': 'timed-out-call', 'type': 'function',
            'function': {'name': 'calculate', 'arguments': '{}'}}]))])
    async def timeout(*args): raise asyncio.TimeoutError()
    monkeypatch.setattr(module, 'call_tool_with_1mcp', timeout)
    _, trajectory, _, exceeded = agent.run_with_server('task')
    assert trajectory[-1]['tool_call_id'] == 'timed-out-call'
    assert exceeded


def test_reader_preserves_failed_cases_and_interrupted_event_tail(tmp_path):
    from member1.read_results import read_results
    case = tmp_path / 'Late-task-156'
    result = case / 'result'
    result.mkdir(parents=True)
    (case / 'run_summary.json').write_text(json.dumps({'task_id': 156, 'version': 'Late',
        'strategy': 'no_update', 'status': 'runner_timeout', 'error': 'runner deadline'}))
    (result / 'trajectory.json').write_text(json.dumps([{'role': 'user', 'content': 'task'}]))
    (result / 'events.jsonl').write_text('{"event":"tool_result","data":{"name":"old_tool","result":"error"}}\n{"event":', encoding='utf-8')
    (tmp_path / 'suite.json').write_text(json.dumps({'runs': [{'version': 'Late', 'task_id': 156}]}))
    rows = list(read_results(tmp_path))
    assert len(rows) == 1
    assert rows[0]['status'] == 'runner_timeout'
    assert rows[0]['answer_record'] is None
    assert rows[0]['trajectory_messages'] == [{'role': 'user', 'content': 'task'}]
    assert rows[0]['events'][0]['data']['name'] == 'old_tool'
    assert rows[0]['read_errors'][0]['line'] == 2


def test_reader_handles_relocated_real_evidence_without_old_absolute_paths():
    from member1.read_results import read_results
    rows = list(read_results(ROOT / 'member1/evidence/stage2/validation'))
    assert len(rows) == 9
    assert {(r['version'], r['task_id']) for r in rows} == {
        (v, task) for v in ('Early', 'Middle', 'Late') for task in (28, 144, 156)}
    assert all(r['answer_record']['trajectory_messages'] for r in rows)


def test_reader_keeps_prior_events_when_timeout_cuts_a_utf8_character(tmp_path):
    from member1.read_results import read_results
    (tmp_path / 'summary.json').write_text(json.dumps({'task_id': 156, 'version': 'Late', 'status': 'runner_timeout'}))
    (tmp_path / 'events.jsonl').write_bytes(b'{"event":"complete"}\n{"event":"partial","data":"\xe4\xb8')
    row = list(read_results(tmp_path))[0]
    assert row['events'] == [{'event': 'complete'}]
    assert row['read_errors']


@pytest.mark.parametrize('terminal', ['runner_timeout', 'cleanup_error'])
def test_all_reader_entrypoints_keep_the_drivers_final_status(tmp_path, terminal):
    from member1.read_results import read_results
    case = tmp_path / 'Late-task-156'
    result = case / 'result'
    result.mkdir(parents=True)
    (result / 'summary.json').write_text(json.dumps({'task_id': 156, 'version': 'Late', 'status': 'running'}))
    (case / 'run_summary.json').write_text(json.dumps({'task_id': 156, 'version': 'Late',
        'status': terminal, 'error': 'authoritative driver error'}))
    (tmp_path / 'suite.json').write_text(json.dumps({'runs': [{'version': 'Late', 'task_id': 156}]}))
    for source in (tmp_path, case, result, result / 'summary.json'):
        row = list(read_results(source))[0]
        assert row['status'] == terminal
        assert row['summary']['error'] == 'authoritative driver error'


def test_agent_accepts_external_usage_instructions():
    from custom.agents.SimpleOpenAIAgent import ChatModel
    agent = ChatModel(model_name='test', api_key='test', knowledge_instructions='Keep the old argument name.')
    assert agent.messages[0]['content'].endswith('Keep the old argument name.')


def test_agent_stops_at_exact_round_budget_and_keeps_final_round_success():
    from custom.agents.SimpleOpenAIAgent import ChatModel
    from openai.types.chat import ChatCompletionMessage
    agent = ChatModel(model_name='test', api_key='test', max_round=1)
    calls = []
    def response(**kwargs):
        calls.append(True)
        return SimpleNamespace(choices=[SimpleNamespace(message=ChatCompletionMessage(role='assistant', content='continue'))])
    agent.complete_with_retry = response
    _, _, stopped, exceeded = agent.run_with_server('task')
    assert len(calls) == 1 and exceeded and not stopped
    agent = ChatModel(model_name='test', api_key='test', max_round=1)
    agent.complete_with_retry = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
        message=ChatCompletionMessage(role='assistant', content='[FINISH] done'))])
    answer, _, stopped, exceeded = agent.run_with_server('task')
    assert stopped and not exceeded and answer == '[FINISH] done'


def test_timeout_is_not_mislabeled_as_startup_failure(tmp_path, monkeypatch):
    from member1 import run_versions
    class Child:
        pid = 99999999
        def poll(self): return None
    class Healthy:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
    monkeypatch.setattr(run_versions.subprocess, 'Popen', lambda *a, **k: Child())
    monkeypatch.setattr(run_versions.urllib.request, 'urlopen', lambda *a, **k: Healthy())
    monkeypatch.setattr(run_versions, 'stop_owned_process', lambda process: None)
    def deadline(*args, **kwargs):
        raise subprocess.TimeoutExpired('run_task', 600)
    monkeypatch.setattr(run_versions.subprocess, 'run', deadline)
    result = run_versions.run_one('Early', 156, tmp_path)
    assert result['status'] == 'runner_timeout'
    assert (tmp_path / 'Early-task-156/run_summary.json').exists()
