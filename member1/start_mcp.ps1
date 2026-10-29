$ErrorActionPreference = 'Stop'
$stageRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $stageRoot
try {
    & '.venv\Scripts\python.exe' -X utf8 'member1/prepare_environment.py'
    if ($LASTEXITCODE -ne 0) { throw 'MCP configuration generation failed' }
    & 'node_modules\.bin\1mcp.cmd' --host 127.0.0.1 --port 3050 --transport http --log-level info --config 'member1/mcp.stage1.local.json' --config-dir 'outputs/1mcp-state' --enable-session-persistence=false --enable-internal-tools=false
    if ($LASTEXITCODE -ne 0) { throw '1mcp failed to start' }
} finally {
    Pop-Location
}
