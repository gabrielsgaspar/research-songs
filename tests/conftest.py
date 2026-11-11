"""Shared test setup: markers that keep CI free of data and network needs."""

import os

import pytest

from songs.common.paths import DATA_ROOT_ENV


def pytest_collection_modifyitems(config, items):
    """Skip `needs_data` tests without a data folder, and `network` tests always."""
    no_data = pytest.mark.skip(reason=f"{DATA_ROOT_ENV} is not set")
    no_network = pytest.mark.skip(reason="tests never call an outside service")
    for item in items:
        if "needs_data" in item.keywords and not os.environ.get(DATA_ROOT_ENV, "").strip():
            item.add_marker(no_data)
        if "network" in item.keywords:
            item.add_marker(no_network)
