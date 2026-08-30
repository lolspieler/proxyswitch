import os
import shutil
import subprocess
from pathlib import Path

WINDOWS = os.name == "nt"


class VpnError(Exception):
    pass


def config_dir():
    override = os.environ.get("PROXYSWITCH_WG_DIR")
    if override:
        return Path(override)
    if WINDOWS:
        base = os.environ.get("ProgramFiles", "C:\\Program Files")
        return Path(base) / "WireGuard" / "Data" / "Configurations"
    return Path("/etc/wireguard")


def _which(name):
    found = shutil.which(name)
    if not found and WINDOWS:
        candidate = Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "WireGuard" / (name + ".exe")
        if candidate.exists():
            return str(candidate)
    if not found:
        raise VpnError(name + " is not installed or not in PATH")
    return found


def _run(args, elevate=False):
    prefix = []
    if elevate and not WINDOWS and shutil.which("sudo"):
        prefix = ["sudo"]
    try:
        done = subprocess.run(prefix + args, capture_output=True, text=True)
    except OSError as exc:
        raise VpnError(str(exc))
    if done.returncode != 0:
        raise VpnError((done.stderr or done.stdout or "command failed").strip())
    return (done.stdout or "").strip()


def available():
    directory = config_dir()
    try:
        names = sorted(p.stem for p in directory.glob("*.conf"))
    except (PermissionError, OSError):
        names = []
    if not names and WINDOWS:
        try:
            names = sorted(p.stem for p in directory.glob("*.conf.dpapi"))
        except (PermissionError, OSError):
            names = []
    return names


def up(name):
    if WINDOWS:
        path = config_dir() / (name + ".conf")
        return _run([_which("wireguard"), "/installtunnelservice", str(path)])
    return _run([_which("wg-quick"), "up", name], elevate=True)


def down(name):
    if WINDOWS:
        return _run([_which("wireguard"), "/uninstalltunnelservice", name])
    return _run([_which("wg-quick"), "down", name], elevate=True)


def status():
    return _run([_which("wg"), "show"], elevate=not WINDOWS)
