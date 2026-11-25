"""Shared test setup: markers that keep CI free of data and network needs."""

import os
from pathlib import Path

import pytest

from songs import cli
from songs.common import config
from songs.common.paths import DATA_ROOT_ENV, resolve_project_root


def pytest_collection_modifyitems(config, items):
    """Skip `needs_data` tests without a data folder, and `network` tests always."""
    no_data = pytest.mark.skip(reason=f"{DATA_ROOT_ENV} is not set")
    no_network = pytest.mark.skip(reason="tests never call an outside service")
    for item in items:
        if "needs_data" in item.keywords and not os.environ.get(DATA_ROOT_ENV, "").strip():
            item.add_marker(no_data)
        if "network" in item.keywords:
            item.add_marker(no_network)


@pytest.fixture(autouse=True)
def no_project_env_file(monkeypatch):
    """Keep the real `.env` and its keys out of every test; other `.env` files still load."""
    load = config.load_env_file
    project_env = (resolve_project_root() / ".env").resolve()

    def load_unless_project_env(path):
        if Path(path).resolve() != project_env:
            load(path)

    monkeypatch.setattr(config, "load_env_file", load_unless_project_env)
    monkeypatch.setattr(cli, "load_env_file", load_unless_project_env)
