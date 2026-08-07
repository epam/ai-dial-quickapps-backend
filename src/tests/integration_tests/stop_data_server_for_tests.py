"""Helpers to start/stop the MCP + REST dual server used by integration tests."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Ports must stay in sync with DualServerRunner defaults in data_server_for_tests.py
REST_PORT = 8002
MCP_PORT = 8003
PORTS = (REST_PORT, MCP_PORT)
PID_FILE = Path(".mcp_rest_server.pid")


def _pids_listening_on_port(port: int) -> set[int]:
    """Return PIDs that currently listen on ``port`` (best-effort, OS-specific)."""
    pids: set[int] = set()
    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            # Example: TCP    0.0.0.0:8002    0.0.0.0:0    LISTENING    12345
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP":
                continue
            local_addr = parts[1]
            state = parts[3].upper() if len(parts) >= 5 else ""
            if state != "LISTENING":
                continue
            if not local_addr.endswith(f":{port}"):
                continue
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                continue
    else:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        for token in result.stdout.split():
            try:
                pids.add(int(token))
            except ValueError:
                continue
    return pids


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def stop_servers() -> None:
    """Stop the dual server by PID file and by freeing known listen ports."""
    pids: set[int] = set()
    if PID_FILE.exists():
        try:
            pids.add(int(PID_FILE.read_text(encoding="utf-8").strip()))
        except ValueError:
            pass
        PID_FILE.unlink(missing_ok=True)

    for port in PORTS:
        pids.update(_pids_listening_on_port(port))

    for pid in sorted(pids):
        print(f"Stopping MCP/REST test server process {pid}...")
        _kill_pid(pid)

    # Brief wait so TIME_WAIT / WinError 10048 does not race the next bind.
    time.sleep(0.5)
    still_busy = {port: _pids_listening_on_port(port) for port in PORTS}
    busy = {port: p for port, p in still_busy.items() if p}
    if busy:
        print(f"Warning: ports still in use after stop: {busy}", file=sys.stderr)
        sys.exit(1)
    print("MCP + REST test servers stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("stop",),
        help="stop: kill PID file process and free ports 8002/8003",
    )
    args = parser.parse_args()
    if args.action == "stop":
        stop_servers()


if __name__ == "__main__":
    main()
