import json
import os
import sys
from pathlib import Path


def _default_dir():
    override = os.environ.get("PROXYSWITCH_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "proxyswitch"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "proxyswitch"
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "proxyswitch"


CONFIG_DIR = _default_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = CONFIG_DIR / "state.json"

DEFAULTS = {
    "listen_host": "127.0.0.1",
    "listen_port": 1080,
    "active": None,
    "profiles": {},
}

VALID_KINDS = ("socks5", "http", "direct")


class ConfigError(Exception):
    pass


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, sort_keys=True)
        fh.write("\n")
    try:
        os.chmod(tmp, 0o600)
    except (OSError, NotImplementedError):
        pass
    tmp.replace(CONFIG_FILE)


def mtime():
    try:
        return CONFIG_FILE.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def add_profile(cfg, name, kind, host=None, port=None, username=None, password=None, note=None):
    if kind not in VALID_KINDS:
        raise ConfigError("unknown profile type: " + str(kind))
    if kind != "direct":
        if not host or not port:
            raise ConfigError("host and port are required for " + kind)
    profile = {"kind": kind}
    if kind != "direct":
        profile["host"] = host
        profile["port"] = int(port)
    if username:
        profile["username"] = username
        profile["password"] = password or ""
    if note:
        profile["note"] = note
    cfg["profiles"][name] = profile
    if cfg.get("active") is None:
        cfg["active"] = name
    return profile


def remove_profile(cfg, name):
    if name not in cfg["profiles"]:
        raise ConfigError("profile not found: " + name)
    del cfg["profiles"][name]
    if cfg.get("active") == name:
        cfg["active"] = next(iter(cfg["profiles"]), None)


def resolve(cfg, name=None):
    wanted = name or cfg.get("active")
    if wanted is None:
        raise ConfigError("no active profile set")
    if wanted == "direct" and wanted not in cfg["profiles"]:
        return wanted, {"kind": "direct"}
    if wanted not in cfg["profiles"]:
        raise ConfigError("profile not found: " + wanted)
    return wanted, cfg["profiles"][wanted]


def describe(name, profile):
    kind = profile.get("kind", "socks5")
    if kind == "direct":
        return name + "  [direct]"
    auth = " auth" if profile.get("username") else ""
    text = name + "  [" + kind + "] " + str(profile.get("host")) + ":" + str(profile.get("port")) + auth
    if profile.get("note"):
        text = text + "  (" + profile["note"] + ")"
    return text
