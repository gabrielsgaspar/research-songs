"""Shared test setup: markers that keep CI free of data and network needs."""

import os
import socket
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


LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "", None})
PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


class NetworkCallError(RuntimeError):
    """A test tried to reach a host outside this computer."""


def _refuse_remote(host):
    if host not in LOCAL_HOSTS:
        raise NetworkCallError(f"tests never call the network; a test tried to reach {host!r}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Refuse every connection and name lookup outside this computer, in every test.

    Proxy settings are cleared too: a proxy on this computer would carry a call outside.
    """
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    connect, connect_ex, getaddrinfo = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
    )

    def checked(method):
        def call(self, address, *args, **kwargs):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                _refuse_remote(address[0])
            return method(self, address, *args, **kwargs)

        return call

    def checked_getaddrinfo(host, *args, **kwargs):
        _refuse_remote(host.decode() if isinstance(host, bytes) else host)
        return getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", checked(connect))
    monkeypatch.setattr(socket.socket, "connect_ex", checked(connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", checked_getaddrinfo)
