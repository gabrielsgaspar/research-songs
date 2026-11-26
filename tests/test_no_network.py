"""The shared test setup refuses every call to a host outside this computer."""

import socket
import urllib.request

import pytest
from conftest import NetworkCallError


def test_a_connection_to_a_remote_host_is_refused():
    with pytest.raises(NetworkCallError, match="example.com"):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(NetworkCallError):
        urllib.request.urlopen("https://example.com", timeout=1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkCallError, match="93.184.215.14"):
            sock.connect(("93.184.215.14", 443))


def test_a_connection_on_this_computer_still_works():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=1):
            pass
