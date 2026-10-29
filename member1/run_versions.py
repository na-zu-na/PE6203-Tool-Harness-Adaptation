"""Launch the real snapshot in a fresh workspace, run the frozen tasks, then stop it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from member1.stage2 import build_runtime_config, create_workspace, manifest, version_info


def stop_owned_process(process):
    if process is None or process.poll() is not None:
        return
    if os.name == 'nt':
        killed = subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if killed.returncode != 0 and process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)


def run_one(version, task_id, suite_root, check_tools=False, knowledge_file=None):
    run_root = suite_root / f'{version}-task-{task_id}'
    run_root.mkdir()
    runtime = run_root / 'runtime'
    runtime.mkdir()
    process = None
    result = {'schema_version': 1, 'version': version, 'task_id': task_id, 'status': 'startup_error', 'run_dir': str(run_root)}
    server_log = (run_root / 'mcp.log').open('w', encoding='utf-8')
    failure_stage = 'startup_error'
    try:
        if knowledge_file is not None:
            from member1.knowledge import load_knowledge
            supplied = load_knowledge(knowledge_file, task_id)
            result.update(strategy=supplied['packet']['strategy'], knowledge_mode='provided_file',
                update_cost=supplied['update_cost'], knowledge={'source_path': str(knowledge_file),
                    'sha256': supplied['sha256'], 'source_version': supplied['packet']['source_version']})
        workspace = create_workspace(run_root)
        config, context = build_runtime_config(version, workspace, [task_id])
        port = version_info(version)['port']
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is occupied; refusing to use an unverified existing server')
        config_path = runtime / 'mcp.json'
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        command = [shutil.which('node'), str(ROOT / 'node_modules/@1mcp/agent/build/index.js'),
            '--host', '127.0.0.1', '--port', str(port), '--transport', 'http', '--log-level', 'warn',
            '--config', str(config_path), '--config-dir', str(runtime),
            '--enable-session-persistence=false', '--enable-internal-tools=false']
        context['config_path'] = str(config_path)
        context['config_sha256'] = hashlib.sha256(config_path.read_bytes()).hexdigest()
        context['launch_command'] = command
        process = subprocess.Popen(command, cwd=workspace, stdout=server_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt')
        context['pid'] = process.pid
        context_path = runtime / 'context.json'
        context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding='utf-8')
        # Synchronous 1mcp startup publishes its listener after backend initialization.
        deadline = time.monotonic() + 45
        while True:
            if process.poll() is not None:
                raise RuntimeError(f'1mcp exited during startup ({process.returncode}); inspect mcp.log')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError('MCP startup timed out; inspect mcp.log')
            time.sleep(0.2)
        invocation = [sys.executable, '-X', 'utf8', str(ROOT / 'member1/run_task.py'),
            '--task-id', str(task_id), '--version', version, '--mcp-url', context['mcp_url'],
            '--runtime-context', str(context_path), '--output-dir', str(run_root / 'result')]
        if check_tools:
            invocation.append('--check-tools')
        if knowledge_file is not None:
            invocation += ['--knowledge-file', str(knowledge_file)]
        failure_stage = 'runner_error'
        with (run_root / 'runner.log').open('w', encoding='utf-8') as log:
            completed = subprocess.run(invocation, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        summary_path = run_root / 'result/summary.json'
        if summary_path.exists():
            result.update(json.loads(summary_path.read_text(encoding='utf-8')))
        else:
            raise RuntimeError(f'Runner exited without a summary ({completed.returncode}); inspect runner.log')
        result['exit_code'] = completed.returncode
    except subprocess.TimeoutExpired as exc:
        partial = run_root / 'result/summary.json'
        if partial.exists():
            try:
                result.update(json.loads(partial.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                pass
        result.update(status='runner_timeout', error=str(exc))
    except Exception as exc:
        result.update(status=failure_stage, error=str(exc))
    finally:
        try:
            stop_owned_process(process)
        except Exception as exc:
            result.update(execution_status=result['status'], status='cleanup_error', cleanup_error=str(exc))
        finally:
            server_log.close()
            result['process_stopped'] = process is None or process.poll() is not None
            (run_root / 'run_summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{version} task {task_id}: {result["status"]}', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', choices=['Early', 'Middle', 'Late', 'all'], default='all')
    parser.add_argument('--task-id', type=int, help='Omit to run every task in the fixed manifest')
    parser.add_argument('--check-tools', action='store_true', help='Validate every required tool without charging model API calls')
    knowledge_args = parser.add_mutually_exclusive_group()
    knowledge_args.add_argument('--knowledge-file', type=Path, help='One packet; requires --task-id')
    knowledge_args.add_argument('--knowledge-dir', type=Path, help='Directory with <task-id>.json for every selected task')
    args = parser.parse_args()
    data = manifest()
    ids = [item['id'] for item in data['tasks']]
    if args.task_id is not None and args.task_id not in ids:
        parser.error(f'Task must belong to the frozen list {ids}')
    task_ids = [args.task_id] if args.task_id is not None else ids
    versions = list(data['versions']) if args.version == 'all' else [args.version]
    supplied = {}
    if args.knowledge_file is not None and args.task_id is None:
        parser.error('--knowledge-file requires --task-id')
    if args.knowledge_file is not None or args.knowledge_dir is not None:
        from member1.knowledge import load_knowledge
        try:
            for task_id in task_ids:
                path = args.knowledge_file if args.knowledge_file is not None else args.knowledge_dir / f'{task_id}.json'
                supplied[task_id] = load_knowledge(path, task_id)
            if len({k['packet']['strategy'] for k in supplied.values()}) != 1:
                raise ValueError('A knowledge directory must use one strategy for this suite')
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    stage_name = 'stage3' if supplied else 'stage2'
    suite = ROOT / 'outputs' / f'{stage_name}-{stamp}-{uuid.uuid4().hex[:8]}'
    suite.mkdir(parents=True)
    frozen, input_records = {}, {}
    if supplied:
        (suite / 'knowledge_inputs').mkdir()
        for task_id, knowledge in supplied.items():
            frozen[task_id] = suite / 'knowledge_inputs' / f'{task_id}.json'
            frozen[task_id].write_bytes(knowledge['raw_bytes'])
            input_records[task_id] = {'source_path': knowledge['source_path'], 'sha256': knowledge['sha256'],
                'snapshot': f'knowledge_inputs/{task_id}.json'}
    suite_record = {'schema_version': 1, 'mode': 'tools_only' if args.check_tools else 'live_model',
        'versions': versions, 'task_ids': task_ids, 'knowledge_inputs': input_records, 'runs': []}
    for version in versions:
        for task_id in task_ids:
            suite_record['runs'].append(run_one(version, task_id, suite, args.check_tools, frozen.get(task_id)))
            (suite / 'suite.json').write_text(json.dumps(suite_record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Suite output: {suite}', flush=True)
    return 0 if all(r['status'] in {'completed', 'tools_ready', 'knowledge_ready'} for r in suite_record['runs']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
