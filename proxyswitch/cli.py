import argparse
import asyncio
import getpass
import json
import os
import sys
import time

from . import config, health, server, vpn

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def supports_color():
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        return bool(os.environ.get("WT_SESSION") or os.environ.get("ANSICON") or os.environ.get("TERM"))
    return True


def color(text, code):
    if not supports_color():
        return text
    return code + text + RESET


def cmd_add(args):
    cfg = config.load()
    password = args.password
    if args.username and password is None:
        password = getpass.getpass("password for " + args.username + ": ")
    config.add_profile(
        cfg,
        args.name,
        args.kind,
        host=args.host,
        port=args.port,
        username=args.username,
        password=password,
        note=args.note,
    )
    config.save(cfg)
    print("saved: " + config.describe(args.name, cfg["profiles"][args.name]))
    return 0


def cmd_import(args):
    cfg = config.load()
    count = 0
    with open(args.file, "r", encoding="utf-8") as fh:
        for index, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                name, profile = parse_uri(line, args.prefix, index)
            except ValueError as exc:
                print("line " + str(index) + " skipped: " + str(exc))
                continue
            cfg["profiles"][name] = profile
            count += 1
    if cfg.get("active") is None and cfg["profiles"]:
        cfg["active"] = next(iter(cfg["profiles"]))
    config.save(cfg)
    print(str(count) + " profiles imported")
    return 0


def parse_uri(line, prefix, index):
    from urllib.parse import unquote, urlparse

    parsed = urlparse(line)
    scheme = parsed.scheme.lower()
    if scheme in ("socks5", "socks5h", "socks"):
        kind = "socks5"
    elif scheme in ("http", "https"):
        kind = "http"
    else:
        raise ValueError("unsupported scheme: " + str(parsed.scheme))
    if not parsed.hostname or not parsed.port:
        raise ValueError("host or port missing")
    profile = {"kind": kind, "host": parsed.hostname, "port": parsed.port}
    if parsed.username:
        profile["username"] = unquote(parsed.username)
        profile["password"] = unquote(parsed.password or "")
    name = parsed.fragment or (prefix + str(index))
    return unquote(name), profile


def cmd_rm(args):
    cfg = config.load()
    config.remove_profile(cfg, args.name)
    config.save(cfg)
    print("removed: " + args.name)
    return 0


def cmd_ls(args):
    cfg = config.load()
    if not cfg["profiles"]:
        print("no profiles yet, add one with: proxyswitch add <name> --kind socks5 --host ... --port ...")
        return 0
    active = cfg.get("active")
    for name in sorted(cfg["profiles"]):
        marker = color("*", GREEN + BOLD) if name == active else " "
        print(marker + " " + config.describe(name, cfg["profiles"][name]))
    print(color("\nlistening on " + str(cfg["listen_host"]) + ":" + str(cfg["listen_port"]), DIM))
    return 0


def cmd_use(args):
    cfg = config.load()
    name, _ = config.resolve(cfg, args.name)
    cfg["active"] = name
    config.save(cfg)
    print("active: " + name)
    print(color("a running server picks this up for new connections automatically", DIM))
    return 0


def cmd_test(args):
    cfg = config.load()
    if args.all:
        targets = sorted(cfg["profiles"].items())
    else:
        name, profile = config.resolve(cfg, args.name)
        targets = [(name, profile)]
    if not targets:
        print("no profiles to test")
        return 1

    results = asyncio.run(health.check_many(targets, want_ip=not args.fast))
    width = max(len(name) for name, _ in targets)
    best = None
    for name, result in sorted(results, key=lambda item: item[0]):
        if result["ok"]:
            line = color("ok  ", GREEN) + name.ljust(width) + "  " + str(round(result["ms"])) + " ms"
            if result["ip"]:
                line += "  exit " + result["ip"]
            if best is None or result["ms"] < best[1]:
                best = (name, result["ms"])
        else:
            line = color("tot ", RED) + name.ljust(width) + "  " + str(result["error"])
        print(line)
    if best and args.switch:
        cfg["active"] = best[0]
        config.save(cfg)
        print("\nswitched to " + best[0])
    return 0


def cmd_run(args):
    try:
        asyncio.run(server.serve(host=args.host, port=args.port, verbose=not args.quiet))
    except OSError as exc:
        print(color("could not bind: " + str(exc), RED))
        return 1
    return 0


def cmd_gui(args):
    from . import gui

    return gui.main()


def cmd_status(args):
    cfg = config.load()
    print("active profile: " + str(cfg.get("active")))
    if not config.STATE_FILE.exists():
        print("server: " + color("not running", RED))
        return 0
    with config.STATE_FILE.open("r", encoding="utf-8") as fh:
        state = json.load(fh)
    uptime = int(time.time() - state["since"])
    print("server: " + color("running", GREEN) + " on " + state["listen"] + " (pid " + str(state["pid"]) + ")")
    print("uptime: " + str(uptime // 3600) + "h " + str((uptime % 3600) // 60) + "m")
    print("connections: " + str(state["connections"]) + " total, " + str(state["active_now"]) + " open, " + str(state["failed"]) + " failed")
    print("traffic: " + human(state["bytes_up"]) + " up / " + human(state["bytes_down"]) + " down")
    return 0


def human(value):
    step = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if step < 1024 or unit == "TiB":
            return ("%.1f " % step) + unit
        step /= 1024
    return str(value)


def cmd_listen(args):
    cfg = config.load()
    if args.host:
        cfg["listen_host"] = args.host
    if args.port:
        cfg["listen_port"] = int(args.port)
    config.save(cfg)
    print("listening on " + cfg["listen_host"] + ":" + str(cfg["listen_port"]))
    print(color("restart the server to apply", DIM))
    return 0


def cmd_vpn(args):
    try:
        if args.action == "ls":
            entries = vpn.available()
            print("\n".join(entries) if entries else "no .conf files found (or no read access)")
        elif args.action == "up":
            vpn.up(args.name)
            print("wireguard " + args.name + " is up")
        elif args.action == "down":
            vpn.down(args.name)
            print("wireguard " + args.name + " is down")
        else:
            output = vpn.status()
            print(output if output else "no active wireguard interface")
    except vpn.VpnError as exc:
        print(color("error: " + str(exc), RED))
        return 1
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="proxyswitch", description="local SOCKS5 router with switchable upstream proxies")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="create a profile")
    add.add_argument("name")
    add.add_argument("--kind", default="socks5", choices=config.VALID_KINDS)
    add.add_argument("--host")
    add.add_argument("--port", type=int)
    add.add_argument("--username")
    add.add_argument("--password")
    add.add_argument("--note")
    add.set_defaults(func=cmd_add)

    imp = sub.add_parser("import", help="import profiles from a file of proxy URIs")
    imp.add_argument("file")
    imp.add_argument("--prefix", default="proxy")
    imp.set_defaults(func=cmd_import)

    rm = sub.add_parser("rm", help="delete a profile")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_rm)

    ls = sub.add_parser("ls", help="list profiles")
    ls.set_defaults(func=cmd_ls)

    use = sub.add_parser("use", help="switch the active profile")
    use.add_argument("name")
    use.set_defaults(func=cmd_use)

    test = sub.add_parser("test", help="check latency and exit IP")
    test.add_argument("name", nargs="?")
    test.add_argument("--all", action="store_true")
    test.add_argument("--fast", action="store_true", help="latency only, skip the exit IP lookup")
    test.add_argument("--switch", action="store_true", help="switch to the fastest profile afterwards")
    test.set_defaults(func=cmd_test)

    run = sub.add_parser("run", help="start the local SOCKS5 server")
    run.add_argument("--host")
    run.add_argument("--port", type=int)
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=cmd_run)

    ui = sub.add_parser("gui", help="open the desktop app")
    ui.set_defaults(func=cmd_gui)

    status = sub.add_parser("status", help="show server runtime info")
    status.set_defaults(func=cmd_status)

    listen = sub.add_parser("listen", help="change the listen address permanently")
    listen.add_argument("--host")
    listen.add_argument("--port", type=int)
    listen.set_defaults(func=cmd_listen)

    wg = sub.add_parser("vpn", help="control wireguard tunnels")
    wg.add_argument("action", choices=["ls", "up", "down", "status"])
    wg.add_argument("name", nargs="?")
    wg.set_defaults(func=cmd_vpn)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as exc:
        print(color("error: " + str(exc), RED))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
