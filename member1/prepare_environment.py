"""Generate machine-local stage-one config from the benchmark's original config."""
import json
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
source = json.loads((root / 'servers/1mcp_config/original/mcp.json').read_text(encoding='utf-8'))
node = shutil.which('node')
if not node:
    raise SystemExit('Node.js is not available on PATH')
server_names = ['@guanxiong/mcp-server-time', 'calculator']
servers = {name: dict(source['mcpServers'][name]) for name in server_names}
servers[server_names[0]].update(command=node, args=[str(root / 'node_modules/@guanxiong/mcp-server-time/index.js')])
scripts = Path(sys.executable).parent
calculator = scripts / ('mcp-server-calculator.exe' if sys.platform == 'win32' else 'mcp-server-calculator')
if not calculator.exists():
    raise SystemExit('Install member1/requirements.txt in the active virtual environment first')
servers['calculator'].update(command=str(calculator), args=[])
# Current 1mcp hashes long/scoped aggregate names. Keep a short runtime alias;
# the source task and its original server identity remain unchanged.
servers['clock'] = servers.pop('@guanxiong/mcp-server-time')
target = root / 'member1/mcp.stage1.local.json'
target.write_text(json.dumps({'mcpServers': servers}, ensure_ascii=False, indent=2), encoding='utf-8')
print(target)
