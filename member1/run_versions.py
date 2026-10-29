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


def run_one(version, task_id, suite_root, check_tools=False):
    run_root = suite_root / f'{version}-task-{task_id}'
    run_root.mkdir()
    runtime = run_root / 'runtime'
    runtime.mkdir()
    process = None
    result = {'version': version, 'task_id': task_id, 'status': 'startup_error', 'run_dir': str(run_root)}
    server_log = (run_root / 'mcp.log').open('w', encoding='utf-8')
    try:
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
        with (run_root / 'runner.log').open('w', encoding='utf-8') as log:
            completed = subprocess.run(invocation, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        summary_path = run_root / 'result/summary.json'
        if summary_path.exists():
            result.update(json.loads(summary_path.read_text(encoding='utf-8')))
        else:
            raise RuntimeError(f'Runner exited without a summary ({completed.returncode}); inspect runner.log')
        result['exit_code'] = completed.returncode
    except Exception as exc:
        result.update(status='startup_error', error=str(exc))
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
    args = parser.parse_args()
    data = manifest()
    ids = [item['id'] for item in data['tasks']]
    if args.task_id is not None and args.task_id not in ids:
        parser.error(f'Task must belong to the frozen list {ids}')
    task_ids = [args.task_id] if args.task_id is not None else ids
    versions = list(data['versions']) if args.version == 'all' else [args.version]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    suite = ROOT / 'outputs' / f'stage2-{stamp}-{uuid.uuid4().hex[:8]}'
    suite.mkdir(parents=True)
    results = [run_one(v, task, suite, args.check_tools) for v in versions for task in task_ids]
    (suite / 'suite.json').write_text(json.dumps({'mode': 'tools_only' if args.check_tools else 'live_model',
        'versions': versions, 'task_ids': task_ids, 'runs': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Suite output: {suite}', flush=True)
    return 0 if all(r['status'] in {'completed', 'tools_ready'} for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
