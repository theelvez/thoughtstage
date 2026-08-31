#!/usr/bin/env bash
# Start the local Thoughtstage API and dashboard with one shared environment.
# Loads a gitignored .env (if present) without overriding names already set in
# this process, activates .venv when it exists, starts thoughtstage serve, then
# pnpm --dir web dev. Open http://127.0.0.1:5173/?view=builder

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
echo "Repo: $root"

load_dotenv() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "No .env file. Mock works without one. Copy .env.example to .env for paid providers."
    return 0
  fi
  local loaded=()
  local line name value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" =~ ^(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
      name="${BASH_REMATCH[2]}"
      value="${BASH_REMATCH[3]}"
      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"
      if [[ "$value" == \"*\" && "$value" == *\" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
        value="${value:1:${#value}-2}"
      fi
      [[ -z "$value" ]] && continue
      if [[ -n "${!name:-}" ]]; then
        continue
      fi
      export "${name}=${value}"
      loaded+=("$name")
    fi
  done < "$path"
  if ((${#loaded[@]})); then
    echo "Loaded from .env (names only): ${loaded[*]}"
  else
    echo "Read .env. No new names were set (empty values or already present in this process)."
  fi
}

wait_for_api() {
  local port="${1:-8000}"
  local i
  for i in $(seq 1 40); do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
        return 0
      fi
    elif command -v python3 >/dev/null 2>&1; then
      if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${port}/api/health', timeout=1)" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 0.25
  done
  echo "thoughtstage serve did not become ready on port ${port}. Is another process using it?" >&2
  return 1
}

load_dotenv "$root/.env"

if [[ -f "$root/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$root/.venv/bin/activate"
  echo "Activated .venv"
else
  echo "No .venv found. Using the current Python environment."
fi

if ! command -v thoughtstage >/dev/null 2>&1; then
  echo "thoughtstage is not on PATH. From the repo root: python -m pip install -e '.[dev]'" >&2
  exit 1
fi
if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is not on PATH. Install Node.js and pnpm, then retry." >&2
  exit 1
fi

if [[ ! -d "$root/web/node_modules" ]]; then
  echo "Installing dashboard dependencies..."
  pnpm --dir web install
fi

echo "Starting thoughtstage serve on port 8000..."
thoughtstage serve &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM

wait_for_api 8000
echo "API ready: http://127.0.0.1:8000/api/health"
echo "Wizard:    http://127.0.0.1:5173/?view=builder"
echo "Observer:  http://127.0.0.1:5173"
pnpm --dir web dev
