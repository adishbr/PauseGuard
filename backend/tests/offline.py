"""Collection-time and fresh-process guards; imports no application code."""

import builtins
import io
import os
import socket
import threading

import psycopg2
from sqlalchemy import event
from sqlalchemy.engine import Engine


class OfflineViolation(AssertionError):
    """Prohibited I/O was attempted."""


def install_guards(patches):
    def forbidden(*args, **kwargs):
        raise OfflineViolation("Network and database access are prohibited in foundation tests.")

    original_socketpair = socket.socketpair
    original_connect = socket.socket.connect
    context = threading.local()

    def internal_socketpair(*args, **kwargs):
        # Windows asyncio needs stdlib's loopback socketpair wake-up pipe.
        context.active = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            context.active = False

    def guarded_connect(sock, address):
        if getattr(context, "active", False):
            return original_connect(sock, address)
        forbidden()

    guarded_connect.pauseguard_guard = True
    patches.setattr(socket, "socketpair", internal_socketpair)
    patches.setattr(socket.socket, "connect", guarded_connect)
    for name in ("connect_ex", "sendto"):
        patches.setattr(socket.socket, name, forbidden)
    patches.setattr(socket, "create_connection", forbidden)
    patches.setattr(socket, "getaddrinfo", forbidden)
    patches.setattr(psycopg2, "connect", forbidden)

    def guarded_open(original):
        def open_file(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                name = os.path.basename(os.fsdecode(file)).lower()
                if name == ".env" or name.startswith(".env."):
                    raise OfflineViolation("Dotenv access is prohibited in foundation tests.")
            return original(file, *args, **kwargs)
        return open_file

    patches.setattr(builtins, "open", guarded_open(builtins.open))
    patches.setattr(io, "open", guarded_open(io.open))
    patches.setattr(os, "open", guarded_open(os.open))
    patches.setenv("PAUSEGUARD_ENVIRONMENT", "test")
    patches.setenv("PAUSEGUARD_MODE", "mock")
    event.listen(Engine, "engine_connect", forbidden)

    def cleanup():
        event.remove(Engine, "engine_connect", forbidden)
        patches.undo()

    return cleanup
