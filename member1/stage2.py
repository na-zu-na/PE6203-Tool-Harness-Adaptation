"""Frozen subset, official snapshot selection, isolated task state and tool routing."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / 'member1/tasks_manifest.json'


def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


def version_info(version):
    data = manifest()
    if version not in data['versions']:
        raise ValueError(f'Unknown version: {version}')
    return data['versions'][version]


def evolution_layers(version):
    return [(layer, json.loads((ROOT / 'src/custom/data/mutation' /
        Path(*(['HYBRID'] * layer)) / 'evolution.json').read_text(encoding='utf-8')))
        for layer in version_info(version)['evolution_layers']]


def create_workspace(run_root):
    workspace = Path(run_root).resolve() / 'workspace'
    workspace.mkdir(parents=True, exist_ok=False)
    for relative in manifest()['fixtures']:
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'anotation_path' / relative, target)
    (workspace / '.task-sources.json').write_text('[]', encoding='utf-8')
    return workspace


def build_runtime_config(version, workspace, task_ids):
    data, info = manifest(), version_info(version)
    selected = {item['id']: item for item in data['tasks']}
    if not task_ids or not set(task_ids).issubset(selected):
        raise ValueError(f'Task IDs must be from frozen list {list(selected)}')
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is missing from PATH')
    services, source_records = {}, {}
    provenance = json.loads((ROOT / 'member1/snapshots/provenance.json').read_text(encoding='utf-8'))
    for server in sorted({s for task_id in task_ids for s in selected[task_id]['services']}):
        service = data['services'][server]
        alias = service['alias']
        config = {'type': 'stdio', 'cwd': str(workspace), 'env': {
            'WORKSPACE_FOLDER_PATHS': str(workspace), 'SOURCES_PATH': str(workspace / '.task-sources.json'),
            'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
        }}
        if service['kind'] == 'node':
            package_root = ROOT / 'node_modules' / service['package']
            if not (package_root / 'package.json').exists():
                raise RuntimeError(f'Run npm ci first: {service["package"]} is missing')
            source = ROOT / 'member1/snapshots' / info['snapshot'] / alias
            # Put the unchanged archive files beneath the installed package so its
            # own nested dependencies resolve correctly on Windows and Linux.
            deployed = package_root / '.mcpevol' / info['snapshot']
            for record in provenance['files']:
                if record['snapshot'] == info['snapshot'] and record['server'] == server:
                    src = ROOT / record['local_path']
                    if hashlib.sha256(src.read_bytes()).hexdigest() != record['sha256']:
                        raise ValueError(f'Snapshot integrity check failed: {record["local_path"]}')
                    dest = deployed / src.relative_to(source)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
            executable = deployed / service['entry']
            config.update(command=node, args=[str(executable)])
            if sys.platform == 'win32' and alias == 'tasks':
                config['args'] = ['--import', (ROOT / 'member1/windows_paths.mjs').as_uri(), str(executable)]
        else:
            scripts = Path(sys.executable).parent
            executable = scripts / (service['package'] + ('.exe' if sys.platform == 'win32' else ''))
            if not executable.exists():
                raise RuntimeError(f'Python tool missing: {service["package"]}')
            config.update(command=str(executable), args=['--local-timezone=America/New_York'] if server == 'time' else [])
        source_records[alias] = {'original_server': server, 'package': service['package'],
            'entry_path': str(executable), 'entry_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
        services[alias] = config
    context = {'version': version, 'snapshot': info['snapshot'], 'task_ids': task_ids,
        'mcp_url': f'http://127.0.0.1:{info["port"]}/mcp', 'services': source_records,
        'workspace': str(workspace), 'manifest_sha256': hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        'artifact_revision': data['artifact_revision'], 'evolution_layers': info['evolution_layers'],
        'benchmark_commit': data['benchmark_commit']}
    if sys.platform == 'win32' and 'tasks' in services:
        context['compatibility_loader_sha256'] = hashlib.sha256((ROOT / 'member1/windows_paths.mjs').read_bytes()).hexdigest()
    return {'mcpServers': services}, context


def validate_context(context, version, url):
    if context.get('version') != version or context.get('mcp_url') != url:
        raise ValueError('Runtime context does not match the requested version and MCP URL')
    if context.get('snapshot') != version_info(version)['snapshot']:
        raise ValueError('Runtime context names the wrong server snapshot')
    if context.get('manifest_sha256') != hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest():
        raise ValueError('The fixed task manifest changed after this environment was prepared')
    if not context.get('services'):
        raise ValueError('Runtime context has no actual server entries')
    for record in context['services'].values():
        if hashlib.sha256(Path(record['entry_path']).read_bytes()).hexdigest() != record['entry_sha256']:
            raise ValueError('Runtime executable changed after startup')


def apply_description_layers(tool, server, version):
    tool = copy.deepcopy(tool)
    for _, layer in evolution_layers(version):
        change = layer.get(server, {})
        if change.get('mutation_type') != 'DESC':
            continue
        detail = change.get(tool['name'], {})
        description = detail.get('tool', detail).get('modified_description')
        if description is not None:
            tool['description'] = description
        for param in detail.get('parameters', []):
            prop = tool['inputSchema'].get('properties', {}).get(param['parameter_name'])
            if prop is not None:
                prop['description'] = param['modified_description']
    return tool


def select_tools(status, task, version):
    data, tools, server_map, routes = manifest(), [], {}, {}
    for server, original_names in task['servers'].items():
        alias = data['services'][server]['alias']
        prefix = alias + '_1mcp_'
        available = {t.name[len(prefix):]: t for t in status.tools if t.name.startswith(prefix)}
        wanted = set(original_names)
        for _, layer in evolution_layers(version):
            change = layer.get(server, {})
            if change.get('mutation_type') == 'TOOL':
                wanted.discard(change.get('deleted_tool_name'))
                wanted.discard(change.get('old_tool_name'))
                wanted.update(n for n in (change.get('new_tool_name'), change.get('migration_target_tool'),
                    change.get('new_tool_config', {}).get('name')) if n)
        for name in sorted(wanted):
            if name not in available:
                raise RuntimeError(f'Required tool missing in {version}: {server}/{name}')
            raw = available[name]
            tool = apply_description_layers({'name': name, 'description': raw.description,
                'inputSchema': raw.inputSchema}, server, version)
            exposed = alias + '__' + name
            tools.append({**tool, 'name': exposed, 'source_name': name, 'source_server': server})
            server_map[exposed] = alias
            routes[exposed] = prefix + name
    return tools, server_map, routes
