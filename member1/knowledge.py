"""Task-scoped JSON handoff from the adaptation author to the benchmark runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from member1.stage2 import manifest
from jsonschema import Draft202012Validator

STRATEGIES = ('no_update', 'full_rewrite', 'selective_patch')
NAME = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def load_knowledge(path, task_id):
    path = Path(path).resolve()
    raw = path.read_bytes()
    try:
        packet = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Knowledge is not UTF-8 JSON: {path}') from exc
    if not isinstance(packet, dict) or type(packet.get('schema_version')) is not int or packet['schema_version'] != 1:
        raise ValueError('Knowledge schema_version must be 1')
    if type(packet.get('task_id')) is not int or packet['task_id'] != task_id:
        raise ValueError('Knowledge task_id does not match the requested task')
    if packet.get('strategy') not in STRATEGIES or packet.get('source_version') not in ('Early', 'Middle', 'Late'):
        raise ValueError('Knowledge strategy or source_version is invalid')
    instructions = packet.get('instructions', '')
    if not isinstance(instructions, str):
        raise ValueError('Knowledge instructions must be a string')
    data = manifest()
    selected = next((t for t in data['tasks'] if t['id'] == task_id), None)
    if selected is None:
        raise ValueError('Knowledge task is outside the frozen subset')
    tools = packet.get('tools')
    if not isinstance(tools, list) or not tools:
        raise ValueError('Knowledge must contain a non-empty tools list')
    server_map, routes = {}, {}
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError('Each tool must be an object')
        name, source_name, server = tool.get('name'), tool.get('source_name'), tool.get('source_server')
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in routes:
            raise ValueError('Tool names must be unique API-compatible names')
        if not isinstance(source_name, str) or not NAME.fullmatch(source_name) or server not in selected['services']:
            raise ValueError('Tool source identity is invalid for this task')
        if not isinstance(tool.get('description'), str) or not isinstance(tool.get('inputSchema'), dict):
            raise ValueError('Tool description and inputSchema are required')
        try:
            Draft202012Validator.check_schema(tool['inputSchema'])
        except Exception as exc:
            raise ValueError(f'Invalid inputSchema for {name}') from exc
        if tool['inputSchema'].get('type') != 'object':
            raise ValueError('Function inputSchema must have type object')
        alias = data['services'][server]['alias']
        server_map[name] = alias
        # Route the supplied old name literally, even if today's server no longer
        # advertises it. Never substitute current schema, names or descriptions.
        routes[name] = alias + '_1mcp_' + source_name
    cost = packet.get('update_cost')
    if cost is not None:
        if not isinstance(cost, dict) or not cost or not set(cost).issubset({'tokens', 'seconds', 'usd'}):
            raise ValueError('update_cost accepts tokens, seconds and/or usd')
        for metric, value in cost.items():
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (metric == 'tokens' and type(value) is not int):
                raise ValueError('Update costs must be finite, nonnegative numbers; tokens must be an integer')
    return {'packet': packet, 'raw_bytes': raw, 'sha256': hashlib.sha256(raw).hexdigest(),
        'source_path': str(path), 'tools': tools, 'server_map': server_map, 'routes': routes,
        'instructions': instructions, 'update_cost': cost}


def export_knowledge(tools_path, output, task_id, version, strategy):
    packet = {'schema_version': 1, 'task_id': task_id, 'source_version': version,
        'strategy': strategy, 'instructions': '',
        'tools': json.loads(Path(tools_path).read_text(encoding='utf-8'))}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids overwriting another member's handoff file.
    with output.open('xb') as stream:
        stream.write((json.dumps(packet, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    try:
        load_knowledge(output, task_id)
    except Exception:
        output.unlink()  # Only the newly created invalid export, never an existing input.
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task-id', type=int, required=True)
    parser.add_argument('--source-version', choices=['Early', 'Middle', 'Late'], required=True)
    parser.add_argument('--strategy', choices=STRATEGIES, required=True)
    args = parser.parse_args()
    print(export_knowledge(args.tools, args.output, args.task_id, args.source_version, args.strategy))


if __name__ == '__main__':
    main()
