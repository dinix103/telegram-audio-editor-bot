"""Offline cache rotation; never run against a live Bot API server.

Use only through the documented Docker Compose maintenance procedure.
The helper requires a dedicated disposable /telegram mount, checks that
the API is unreachable, and refuses symlinks or alternate root paths.
"""

import argparse
import shutil
import socket
from pathlib import Path


def purge(root: Path, confirmed: bool):
    if not confirmed or root != Path("/telegram") or root.is_symlink() or not root.is_dir():
        raise RuntimeError("Requires offline dedicated /telegram volume and explicit confirmation")
    try:
        with socket.create_connection(("telegram-bot-api", 8081), timeout=3):
            raise RuntimeError("Bot API is still running; refusing cleanup")
    except OSError:
        pass
    for child in root.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    print("Offline Bot API volume cleared. No working-job volumes were touched.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-server-stopped", action="store_true")
    args = parser.parse_args()
    purge(Path("/telegram"), args.confirm_server_stopped)
