"""Read single results or a portable suite and export all cases as JSONL."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def read_results(source):
    source = Path(source).resolve()
    if source.is_file():
        if source.name not in ('suite.json', 'run_summary.json', 'summary.json'):
            raise ValueError('Use a suite/result directory or its suite.json/run_summary.json/summary.json')
        source = source.parent
    if source.name == 'result' and (source.parent / 'run_summary.json').exists():
        # The driver may add timeout/cleanup status after the child is gone.
        # Reading its result/ must not resurrect the child's stale "running".
        source = source.parent
    suite_file = source / 'suite.json'
    if suite_file.exists():
        suite = json.loads(suite_file.read_text(encoding='utf-8-sig'))
        # Use locations within the supplied archive, not historical absolute paths.
        cases = [source / f'{r["version"]}-task-{r["task_id"]}' for r in suite['runs']]
    else:
        cases = [source]
    for case in cases:
        result = case / 'result' if (case / 'run_summary.json').exists() else case
        metadata = case / 'run_summary.json' if (case / 'run_summary.json').exists() else result / 'summary.json'
        summary = json.loads(metadata.read_text(encoding='utf-8-sig'))
        read_errors = []
        def read_json(path, default=None):
            if not path.exists():
                return default
            try:
                return json.loads(path.read_text(encoding='utf-8-sig'))
            except (UnicodeError, json.JSONDecodeError) as exc:
                read_errors.append({'file': path.name, 'error': str(exc)})
                return default
        answer_path = result / 'ANSWER' / f'{summary["task_id"]}.json'
        answer = read_json(answer_path)
        trajectory = answer.get('trajectory_messages', []) if answer is not None else read_json(result / 'trajectory.json', [])
        events = []
        event_file = result / 'events.jsonl'
        if event_file.exists():
            event_bytes = event_file.read_bytes()
            try:
                event_text = event_bytes.decode('utf-8-sig')
            except UnicodeDecodeError as exc:
                read_errors.append({'file': 'events.jsonl', 'error': 'incomplete or invalid UTF-8', 'byte_offset': exc.start})
                event_text = event_bytes.decode('utf-8-sig', errors='replace')
            for number, line in enumerate(event_text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    read_errors.append({'file': 'events.jsonl', 'line': number, 'raw': line, 'error': str(exc)})
        yield {'schema_version': 1, 'task_id': summary['task_id'], 'version': summary['version'],
            'strategy': summary.get('strategy'), 'status': summary['status'],
            'knowledge': summary.get('knowledge'), 'update_cost': summary.get('update_cost'),
            'summary': summary, 'answer_record': answer, 'trajectory_messages': trajectory,
            'events': events, 'read_errors': read_errors,
            'source_files': {'summary': metadata.relative_to(source).as_posix(),
                'answer': answer_path.relative_to(source).as_posix() if answer_path.exists() else None,
                'events': event_file.relative_to(source).as_posix() if event_file.exists() else None}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    output = args.output.open('x', encoding='utf-8') if args.output else sys.stdout
    count = 0
    try:
        for row in read_results(args.source):
            output.write(json.dumps(row, ensure_ascii=False) + '\n')
            count += 1
    finally:
        if args.output:
            output.close()
    print(f'Read {count} cases', file=sys.stderr)


if __name__ == '__main__':
    main()
