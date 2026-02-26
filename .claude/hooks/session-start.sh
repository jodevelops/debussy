#!/bin/bash
set -euo pipefail

# Only run in remote (web) environment
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Install all dependencies (core + optional groups)
pip install pandas">=2.0" pydantic">=2.0" \
    fastapi">=0.100" "uvicorn[standard]>=0.20" python-multipart">=0.0.6" \
    httpx">=0.24" \
    pytest">=7.0" pytest-cov">=4.0" ruff">=0.1" \
    --quiet

# Set PYTHONPATH so tests/linter/CLI work without prefix
echo 'export PYTHONPATH="'"$CLAUDE_PROJECT_DIR"'/src"' >> "$CLAUDE_ENV_FILE"
