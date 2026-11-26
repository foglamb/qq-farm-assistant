#!/usr/bin/env python3
"""Release only Docker's userland forwarding for host port 3009.

The Pad container itself is deliberately left running. The integrated web service
connects directly to the container's private address afterwards.
"""
import os
import signal
import subprocess
from pathlib import Path

try:
    container_ip = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "qq-farm-pad-login"],
        text=True,
    ).strip()
    if container_ip:
        subprocess.run([
            "iptables", "-t", "nat", "-D", "DOCKER", "!", "-i", "docker0",
            "-p", "tcp", "-m", "tcp", "--dport", "3009", "-j", "DNAT",
            "--to-destination", f"{container_ip}:8080",
        ], check=False)
except (FileNotFoundError, subprocess.SubprocessError):
    pass

for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    try:
        argv = (entry / "cmdline").read_bytes().split(b"\0")
        if not argv or argv[0] != b"/usr/bin/docker-proxy":
            continue
        values = [value.decode() for value in argv if value]
        if "-host-port" in values and values[values.index("-host-port") + 1] == "3009":
            os.kill(int(entry.name), signal.SIGTERM)
            print(f"Stopped docker-proxy pid={entry.name} for port 3009")
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError):
        pass
