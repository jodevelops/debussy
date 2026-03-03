"""
API route modules for Debussy.

Each module exports a FastAPI APIRouter that is registered in app.py.
Shared state (datasets, workspace, config/provider factory) is accessed
via dependency-injection helpers imported from kwb.api.deps.
"""
