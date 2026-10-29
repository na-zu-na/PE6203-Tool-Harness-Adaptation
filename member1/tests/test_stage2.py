import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from mcp.types import ListToolsResult, Tool

ROOT = Path(__file__).resolve().parents[2]


def test_real_snapshot_entries_differ_between_versions(tmp_path):
    from member1.stage2 import build_runtime_config
    entries = []
    for version in ('Early', 'Middle', 'Late'):
        config, context = build_runtime_config(version, tmp_path / version, [156])
        executable = Path(config['mcpServers']['clock']['args'][0])
        entries.append(hashlib.sha256(executable.read_bytes()).hexdigest())
        assert context['version'] == version
        assert context['services']['clock']['entry_sha256'] == entries[-1]
        assert config['mcpServers']['clock']['cwd'] == str((tmp_path / version).resolve())
    assert len(set(entries)) == 3  # A relabelled original server must fail this check.


def test_fresh_workspace_restores_original_files_and_empty_task_registry(tmp_path):
    from member1.stage2 import create_workspace
    first = create_workspace(tmp_path / 'first')
    (first / 'txt/log_today.txt').write_text('modified', encoding='utf-8')
    (first / 'tasks.md').write_text('previous task', encoding='utf-8')
    second = create_workspace(tmp_path / 'second')
    assert (second / 'txt/log_today.txt').read_bytes() == (ROOT / 'anotation_path/txt/log_today.txt').read_bytes()
    assert not (second / 'tasks.md').exists()
    assert json.loads((second / '.task-sources.json').read_text()) == []


def test_description_layers_are_applied_without_editing_actual_tool_schema():
    from member1.stage2 import apply_description_layers
    original = {'name': 'convert_time', 'description': 'original',
                'inputSchema': {'type': 'object', 'properties': {'sourceTimezone': {'type': 'string'}}}}
    before = copy.deepcopy(original)
    result = apply_description_layers(original, 'time-mcp', 'Middle')
    assert result['description'] == 'Convert a time from one timezone to another.'
    assert result['inputSchema']['properties']['sourceTimezone']['description'] == 'The source timezone of the input time.'
    assert original == before
    assert apply_description_layers(original, 'time-mcp', 'Early') == before


def test_duplicate_tool_names_keep_distinct_routes():
    from member1.stage2 import select_tools
    from member1.run_task import load_task
    status = ListToolsResult(tools=[Tool(name=n, description='test', inputSchema={'type': 'object', 'properties': {}})
        for n in ('time_mcp_1mcp_current_time', 'time_mcp_1mcp_convert_time',
                  'time_py_1mcp_get_current_time', 'time_py_1mcp_convert_time')])
    tools, server_map, routes = select_tools(status, load_task(144), 'Early')
    assert len({t['name'] for t in tools}) == 4
    assert routes['time_mcp__convert_time'] == 'time_mcp_1mcp_convert_time'
    assert routes['time_py__convert_time'] == 'time_py_1mcp_convert_time'


def test_invalid_version_and_unfrozen_task_are_rejected(tmp_path):
    from member1.stage2 import build_runtime_config
    with pytest.raises(ValueError):
        build_runtime_config('iter99', tmp_path, [156])
    with pytest.raises(ValueError):
        build_runtime_config('Early', tmp_path, [3])


def test_runtime_context_cannot_relabel_a_different_snapshot(tmp_path):
    from member1.stage2 import validate_context
    context = {'version': 'Early', 'mcp_url': 'http://127.0.0.1:3051/mcp'}
    with pytest.raises(ValueError):
        validate_context(context, 'Late', 'http://127.0.0.1:3051/mcp')


def test_middle_catalog_does_not_invent_later_tools_from_directory_names():
    # The official iter3 archive has get_time_info parameter additions, but does
    # not yet advertise convert_timezone. Metadata must align with actual bytes.
    from member1.stage2 import select_tools
    from member1.run_task import load_task
    status = ListToolsResult(tools=[Tool(name=n, description='test', inputSchema={'type': 'object', 'properties': {}})
        for n in ('clock_1mcp_get_current_time', 'clock_1mcp_get_time_info', 'calculator_1mcp_calculate')])
    tools, _, routes = select_tools(status, load_task(156), 'Middle')
    assert len(tools) == 3
    assert not any('convert_timezone' in route for route in routes.values())


def test_namespaced_model_tool_reaches_its_explicit_mcp_route(monkeypatch):
    from custom.agents import SimpleOpenAIAgent as module
    from openai.types.chat import ChatCompletionMessage
    from mcp.types import CallToolResult, TextContent
    from types import SimpleNamespace
    received = []
    agent = module.ChatModel(model_name='test', api_key='test', stop_on_final_answer=True,
        tool_server_map={'time_mcp__convert_time': 'time_mcp'},
        tool_routes={'time_mcp__convert_time': 'time_mcp_1mcp_convert_time'})
    messages = iter([
        ChatCompletionMessage(role='assistant', content=None, tool_calls=[{
            'id': 'call1', 'type': 'function', 'function': {'name': 'time_mcp__convert_time', 'arguments': '{}'}}]),
        ChatCompletionMessage(role='assistant', content='converted'),
    ])
    agent.complete_with_retry = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=next(messages))])
    async def actual_route(name, arguments, url):
        received.append(name)
        return CallToolResult(content=[TextContent(type='text', text='converted')])
    monkeypatch.setattr(module, 'call_tool_with_1mcp', actual_route)
    answer, _, stopped, _ = agent.run_with_server('convert')
    assert answer == 'converted' and stopped
    assert received == ['time_mcp_1mcp_convert_time']


def test_system_prompt_points_tools_at_the_isolated_workspace(tmp_path):
    from custom.agents.SimpleOpenAIAgent import ChatModel
    agent = ChatModel(model_name='test', api_key='test', file_root=str(tmp_path))
    assert str(tmp_path) in agent.messages[0]['content']
    assert './anotation_path' not in agent.messages[0]['content']


@pytest.mark.skipif(os.name != 'nt', reason='Windows absolute ESM paths are a Windows compatibility case')
def test_windows_loader_imports_absolute_paths_without_patching_snapshot_code(tmp_path):
    target = tmp_path / 'metadata.json'
    target.write_text('{"name":"snapshot"}', encoding='utf-8')
    code = f'const m = await import({json.dumps(str(target))}, {{with:{{type:"json"}}}}); const lib=await import("lodash"); console.log(m.default.name, lib.default.camelCase("some value"));'
    result = subprocess.run(['node', '--import', (ROOT / 'member1/windows_paths.mjs').as_uri(),
        '--input-type=module', '-e', code], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'snapshot someValue'


def test_cleanup_failure_still_saves_run_summary(tmp_path, monkeypatch):
    from member1 import run_versions
    # Only the external process boundary is replaced. The real runner must
    # create state and persist its summary even when OS cleanup raises.
    class ExitedChild:
        pid = 99999999
        def poll(self):
            return 9
    monkeypatch.setattr(run_versions.subprocess, 'Popen', lambda *args, **kwargs: ExitedChild())
    def failed_cleanup(process):
        raise subprocess.TimeoutExpired('owned-process-wait', 15)
    monkeypatch.setattr(run_versions, 'stop_owned_process', failed_cleanup)
    result = run_versions.run_one('Early', 156, tmp_path, check_tools=True)
    saved = json.loads((tmp_path / 'Early-task-156/run_summary.json').read_text(encoding='utf-8'))
    assert saved['status'] == 'cleanup_error'
    assert saved['execution_status'] == 'startup_error'
    assert '15' in saved['cleanup_error']
    assert result['status'] == saved['status']
