"""
Shared pytest fixtures/config.

The whole suite is designed to run with zero setup: `pip install -r
requirements.txt && pytest` from `backend/`, no database, no API key,
nothing. That's only possible because the vast majority of what actually
broke this build (see README.md's dated bug list) was a pure computation or
prompt-construction bug — fixable, and testable, entirely in Python with no
network call at all. `pytest.ini`'s `integration` marker is the honest
exception: a handful of the highest-value fixes are prompt-*wording*
regressions (an LLM narrating two correct numbers in the wrong order, an
over-hedging disclaimer) that genuinely can't be verified without a real
call — those are marked explicitly and skipped automatically here unless
OPENAI_API_KEY is actually set, rather than either silently costing money
in CI or silently not existing at all.

Note on what "set" means in practice: config.py calls load_dotenv() at
import time, and collecting any test module that (transitively) imports
config populates os.environ from backend/.env as a side effect before this
hook runs — so on this dev machine, where .env has a real key, a bare
`pytest` already includes the integration tests, not just `pytest -m
integration`. That's the intended behavior (run for real whenever a key is
actually available, in .env or the shell), just worth knowing before
assuming a plain `pytest` run is always free.
"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.getenv("OPENAI_API_KEY"):
        return  # real key present — let integration tests run
    skip_integration = pytest.mark.skip(reason="OPENAI_API_KEY not set — run with a real key to include this")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
