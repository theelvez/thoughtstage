#Requires -Version 5.1
<#
.SYNOPSIS
  Start the local Thoughtstage API and dashboard with one shared environment.

.DESCRIPTION
  Loads a gitignored .env (if present) without overriding names already set in
  this process, activates .venv when it exists, starts thoughtstage serve, then
  pnpm --dir web dev. Open http://127.0.0.1:5173/?view=builder
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host "No .env file. Mock works without one. Copy .env.example to .env for paid providers."
        return
    }

    $loaded = New-Object System.Collections.Generic.List[string]
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line -match '^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $name = $Matches[1]
            $value = $Matches[2].Trim()
            if (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            ) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            if ([string]::IsNullOrEmpty($value)) {
                continue
            }
            $existing = [Environment]::GetEnvironmentVariable($name, "Process")
            if (-not [string]::IsNullOrEmpty($existing)) {
                continue
            }
            Set-Item -Path "Env:$name" -Value $value
            $loaded.Add($name)
        }
    }
    if ($loaded.Count -gt 0) {
        Write-Host ("Loaded from .env (names only): " + ($loaded -join ", "))
    } else {
        Write-Host "Read .env. No new names were set (empty values or already present in this process)."
    }
}

function Wait-ThoughtstageApi {
    param([int]$Port = 8000, [int]$Attempts = 40)

    $uri = "http://127.0.0.1:$Port/api/health"
    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    throw "thoughtstage serve did not become ready on port $Port. Is another process using it?"
}

$Root = Get-RepoRoot
Set-Location -LiteralPath $Root
Write-Host "Repo: $Root"

Import-DotEnv -Path (Join-Path $Root ".env")

$activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path -LiteralPath $activate) {
    . $activate
    Write-Host "Activated .venv"
} else {
    Write-Host "No .venv found. Using the current Python environment."
}

$thoughtstage = Get-Command thoughtstage -ErrorAction SilentlyContinue
if (-not $thoughtstage) {
    throw "thoughtstage is not on PATH. From the repo root: python -m pip install -e `".[dev]`""
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "pnpm is not on PATH. Install Node.js and pnpm, then retry."
}

if (-not (Test-Path -LiteralPath (Join-Path $Root "web\node_modules"))) {
    Write-Host "Installing dashboard dependencies..."
    pnpm --dir web install
}

Write-Host "Starting thoughtstage serve on port 8000..."
$api = Start-Process -FilePath $thoughtstage.Source -ArgumentList "serve" -WorkingDirectory $Root -PassThru -NoNewWindow
try {
    Wait-ThoughtstageApi
    Write-Host "API ready: http://127.0.0.1:8000/api/health"
    Write-Host "Wizard:    http://127.0.0.1:5173/?view=builder"
    Write-Host "Observer:  http://127.0.0.1:5173"
    pnpm --dir web dev
} finally {
    if ($null -ne $api -and -not $api.HasExited) {
        Write-Host "Stopping thoughtstage serve..."
        Start-Process -FilePath "taskkill" -ArgumentList "/PID",$api.Id,"/T","/F" -Wait -WindowStyle Hidden | Out-Null
    }
}
