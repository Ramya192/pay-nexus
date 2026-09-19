"""Application Insights wiring (api/main.py, config.py) is opt-in, gated on
APPLICATIONINSIGHTS_CONNECTION_STRING actually being set. Every other test in
this suite runs with it unset, so this file is the only place that gate
actually gets exercised — a regression here (e.g. the guard silently becoming
unconditional) would otherwise only surface as a crash against the real
deployed App Service, not in CI.

Both real calls (`configure_azure_monitor`, `FastAPIInstrumentor.instrument_app`)
are mocked here rather than actually invoked: `configure_azure_monitor` does
real credential/endpoint resolution over the network even against a
syntactically-valid fake connection string (confirmed live -- it hangs
rather than erroring with no network route available), which is exactly the
kind of real-network dependency this suite's zero-setup, zero-network-call
unit tests deliberately avoid (see conftest.py's module docstring). What
actually needs regression protection is PayNexus's own guard logic -- does it
call through when the connection string is set, and skip cleanly when it
isn't -- not whether the Azure SDK's internals work, which is a live/manual
check against a real resource, same as this project's other "verify live"
checks.
"""

import sys
from unittest.mock import MagicMock

import pytest

from config import config as _config


@pytest.fixture
def _reload_main(monkeypatch):
    """Re-executes api/main.py's module-level code under a patched config
    value and mocked Azure Monitor entry points, then restores both -- so
    this test can't leak a mocked module or a flipped config flag into any
    test that runs after it."""

    def _do(connection_string: str) -> tuple[MagicMock, MagicMock]:
        monkeypatch.setattr(_config, "APPLICATIONINSIGHTS_CONNECTION_STRING", connection_string)

        configure_mock = MagicMock()
        instrument_mock = MagicMock()
        monkeypatch.setattr(
            "azure.monitor.opentelemetry.configure_azure_monitor", configure_mock, raising=True
        )
        monkeypatch.setattr(
            "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app",
            instrument_mock,
            raising=True,
        )

        import api.main  # ensure it's in sys.modules at least once

        import importlib

        importlib.reload(api.main)
        return configure_mock, instrument_mock

    yield _do

    # Always reload once more with the gate off, so later tests import the
    # real (unmocked) api.main again regardless of which case ran last.
    monkeypatch.setattr(_config, "APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    import importlib

    importlib.reload(sys.modules["api.main"])


def test_apm_off_by_default_skips_both_calls(_reload_main):
    configure_mock, instrument_mock = _reload_main("")
    configure_mock.assert_not_called()
    instrument_mock.assert_not_called()


def test_apm_enabled_wires_both_calls_with_the_connection_string(_reload_main):
    fake_conn_str = (
        "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
        "IngestionEndpoint=https://eastus-0.in.applicationinsights.azure.com/"
    )
    configure_mock, instrument_mock = _reload_main(fake_conn_str)

    configure_mock.assert_called_once_with(connection_string=fake_conn_str)
    instrument_mock.assert_called_once()
