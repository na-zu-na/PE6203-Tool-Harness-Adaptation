"""Run one unchanged MCPEvol-Bench task with the upstream ChatModel."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def load_task(task_id: int) -> dict:
    source = ROOT / 'src/custom/data/test_cases'
    selected = json.loads((source / 'chosen_idx.json').read_text(encoding='utf-8'))
    if task_id not in {item['idx'] for item in selected['samples']}:
        raise ValueError(f'Task {task_id} is not in the official 201-task selection')
    tasks = json.loads((source / 'test_cases.json').read_text(encoding='utf-8'))
    task = next(t for t in tasks if t['idx'] == task_id)
    # Match upstream clean_test_case; do not expose source answers or trajectories.
    return {key: task[key] for key in ('idx', 'question', 'servers', 'tool_calls')}


async def discover_tools(url: str):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.list_tools()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', type=int, default=156)
    parser.add_argument('--mcp-url', default='http://127.0.0.1:3050/mcp')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--check-tools', action='store_true', help='Real MCP check without a model request')
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    output = args.output_dir or ROOT / 'outputs' / f'stage1-{run_id}'
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    key = os.environ.get('ARK_API_KEY', '').strip()

    def safe_json(data):
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        return text.replace(key, '[REDACTED]') if key else text

    def save(name, data):
        (output / name).write_text(safe_json(data), encoding='utf-8')

    events = []
    def record(kind, value):
        item = {'time_utc': datetime.now(timezone.utc).isoformat(), 'event': kind, 'data': value}
        events.append(item)
        with (output / 'events.jsonl').open('a', encoding='utf-8') as stream:
            text = json.dumps(item, ensure_ascii=False, default=str)
            stream.write((text.replace(key, '[REDACTED]') if key else text) + '\n')

    summary = {
        'run_id': run_id, 'task_id': args.task_id, 'version': 'Early',
        'environment': 'original config subset, resolved packages in member1 lock files',
        'strategy': 'initial_knowledge_stage1', 'status': 'running',
        'base_url': os.environ.get('ARK_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3'),
        'model': os.environ.get('ARK_MODEL', 'deepseek-v4-flash-ga-260731'),
        'temperature': 0.2, 'max_completion_tokens': 4096,
        'stop_policy': 'final_text_after_tool_result',
        'python': sys.version, 'platform': platform.platform(),
        'mcp_url': args.mcp_url, 'mode': 'tools_only' if args.check_tools else 'live_model',
        'started_utc': datetime.now(timezone.utc).isoformat(),
    }
    save('summary.json', summary)
    stage = 'configuration_error'
    agent = None
    try:
        if not args.check_tools and not key:
            raise ValueError('ARK_API_KEY is missing. Set it in .env or the process environment.')
        task = load_task(args.task_id)
        save('task.json', task)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        summary['benchmark_commit'] = commit
        source_bytes = (ROOT / 'src/custom/data/test_cases/test_cases.json').read_bytes()
        summary['task_source_sha256'] = hashlib.sha256(source_bytes).hexdigest()
        stage = 'mcp_connection_error'
        status = asyncio.run(discover_tools(args.mcp_url))
        from custom.utils.test_utils import get_1mcp_server_tools, generate_tree_string
        tools, server_map = [], {}
        for server, names in task['servers'].items():
            runtime_server = {'@guanxiong/mcp-server-time': 'clock'}.get(server, server)
            available = {t.name: t for t in get_1mcp_server_tools(status, runtime_server)}
            for name in names:
                if name not in available:
                    raise RuntimeError(f'Required tool missing: {server} / {name}')
                if name in server_map:
                    raise RuntimeError(f'Duplicate tool name requires explicit routing: {name}')
                t = available[name]
                tools.append({'name': t.name, 'description': t.description, 'inputSchema': t.inputSchema})
                server_map[name] = runtime_server
        save('tools.json', tools)
        record('tools_discovered', {'count': len(tools), 'server_map': server_map})
        if args.check_tools:
            # Calls are deterministic connectivity probes, not model-generated results.
            from custom.agents.SimpleOpenAIAgent import call_tool_with_1mcp
            probes = [('clock_1mcp_get_current_time', {'timezone': 'Asia/Tokyo'}),
                      ('calculator_1mcp_calculate', {'expression': '1+2*3'})]
            for name, arguments in probes:
                result = asyncio.run(call_tool_with_1mcp(name, arguments, args.mcp_url))
                record('manual_tool_probe', {'name': name, 'arguments': arguments, 'result': result.model_dump(mode='json')})
                if result.isError:
                    raise RuntimeError(f'MCP probe returned an error: {name}')
            summary['status'] = 'tools_ready'
        else:
            stage = 'model_error'
            from custom.agents.SimpleOpenAIAgent import ChatModel
            agent = ChatModel(
                model_name=summary['model'], model_url=summary['base_url'], api_key=key,
                temperature=0.2, max_new_tokens=4096, tools=tools,
                max_round=max(10, 2 * len(tools)), tool_server_map=server_map,
                file_exists=generate_tree_string(ROOT / 'anotation_path'),
                mcp_server_url=args.mcp_url, event_callback=record,
                stop_on_final_answer=True,
            )
            summary['max_round'] = agent.max_round
            record('task_started', {'question': task['question'], 'system_prompt': agent.messages[0]})
            answer, trajectory, stopped, exceeded = agent.run_with_server(task['question'])
            result = {**task, 'answer': answer, 'trajectory_messages': trajectory,
                      'stop': stopped, 'exceeded': exceeded, 'involved_tools': tools}
            (output / 'ANSWER').mkdir()
            save(f'ANSWER/{args.task_id}.json', result)
            model_errors = [e for e in events if e['event'] == 'model_error']
            tool_errors = [e for e in events if e['event'] == 'tool_error']
            raw_results = [e['data']['result'] for e in events if e['event'] == 'tool_result']
            summary.update({
                'tool_calls': len(raw_results),
                'successful_tool_results': sum(isinstance(r, dict) and not r.get('isError', False) for r in raw_results),
                'stop': stopped, 'exceeded': exceeded,
            })
            if model_errors:
                summary.update(status='model_error', error=model_errors[-1]['data']['error'])
            elif tool_errors or any(isinstance(r, dict) and r.get('isError') for r in raw_results):
                summary['status'] = 'tool_error'
            elif exceeded:
                summary['status'] = 'round_limit'
            elif stopped and raw_results:
                summary['status'] = 'completed'
            else:
                summary['status'] = 'incomplete'
    except Exception as exc:
        summary.update(status=stage, error=str(exc))
        record(stage, {'error': str(exc)})
        if agent is not None:
            save('partial_trajectory.json', agent.messages)
    finally:
        summary['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save('summary.json', summary)
    print(f"Status: {summary['status']}\nOutput: {output}")
    return 0 if summary['status'] in {'completed', 'tools_ready'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
