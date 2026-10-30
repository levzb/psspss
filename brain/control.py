"""The cat runs in the background; `psspss` talks to it over a Unix socket. Its log, lock and
settings live next to the socket in ~/.psspss/."""
import json
import os
import socket

HOME = os.path.expanduser('~/.psspss')
SOCK = os.path.join(HOME, 'sock')
LOG = os.path.join(HOME, 'log')
LOCK = os.path.join(HOME, 'lock')
PREFS = os.path.join(HOME, 'prefs.json')


def send(line, timeout=3.0):
    """The running cat's answer to a command, or None if no cat is running."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
        s.sendall(line.encode() + b'\n')
        data = b''
        while chunk := s.recv(4096):
            data += chunk
        return data.decode()
    except (FileNotFoundError, ConnectionRefusedError):
        return None
    finally:
        s.close()


class Server:
    """Non-blocking: the app polls it from its timer."""

    def __init__(self):
        os.makedirs(HOME, exist_ok=True)
        if os.path.exists(SOCK):
            os.unlink(SOCK)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(SOCK)
        self.sock.listen(4)
        self.sock.setblocking(False)

    def poll(self, handle):
        """Answer every waiting command with handle(line) -> reply."""
        while True:
            try:
                conn, _ = self.sock.accept()
            except BlockingIOError:
                return
            with conn:
                conn.settimeout(1.0)
                try:
                    line = conn.makefile().readline().strip()
                    conn.sendall(handle(line).encode())
                except OSError:
                    pass

    def close(self):
        self.sock.close()
        if os.path.exists(SOCK):
            os.unlink(SOCK)


def prefs():
    try:
        with open(PREFS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_prefs(**changes):
    os.makedirs(HOME, exist_ok=True)
    merged = dict(prefs(), **changes)            # read before 'w' empties the file
    with open(PREFS, 'w') as f:
        json.dump(merged, f)
