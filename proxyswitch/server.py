import asyncio
import ipaddress
import json
import os
import signal
import threading
import time

from . import config
from .upstream import UpstreamError, open_through

REPLY_OK = 0x00
REPLY_GENERAL = 0x01
REPLY_NOT_ALLOWED = 0x02
REPLY_HOST_UNREACHABLE = 0x04
REPLY_REFUSED = 0x05
REPLY_CMD_UNSUPPORTED = 0x07
REPLY_ATYP_UNSUPPORTED = 0x08

BUFFER = 65536


class Router:
    def __init__(self, verbose=False, sink=None):
        self.cfg = config.load()
        self.stamp = config.mtime()
        self.verbose = verbose
        self.sink = sink
        self.started = time.time()
        self.connections = 0
        self.active_now = 0
        self.failed = 0
        self.bytes_up = 0
        self.bytes_down = 0
        self.listen = ""

    def refresh(self):
        stamp = config.mtime()
        if stamp != self.stamp:
            self.cfg = config.load()
            self.stamp = stamp
            self.log("config reloaded, active profile: " + str(self.cfg.get("active")))

    def log(self, message):
        if self.sink is not None:
            self.sink(message)
        if self.verbose:
            print(time.strftime("[%H:%M:%S] ") + message, flush=True)

    def snapshot(self):
        return {
            "pid": os.getpid(),
            "listen": self.listen or (str(self.cfg.get("listen_host")) + ":" + str(self.cfg.get("listen_port"))),
            "active": self.cfg.get("active"),
            "since": self.started,
            "connections": self.connections,
            "active_now": self.active_now,
            "failed": self.failed,
            "bytes_up": self.bytes_up,
            "bytes_down": self.bytes_down,
        }

    def write_state(self):
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = config.STATE_FILE.with_name(config.STATE_FILE.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.snapshot(), fh, indent=2)
        tmp.replace(config.STATE_FILE)

    async def state_loop(self, interval=1.0):
        while True:
            try:
                self.write_state()
            except OSError:
                pass
            await asyncio.sleep(interval)


def clear_state():
    try:
        config.STATE_FILE.unlink()
    except (FileNotFoundError, OSError):
        pass


async def read_request_address(reader):
    head = await reader.readexactly(4)
    version, command, _, atyp = head
    if version != 5:
        raise ValueError("not SOCKS5")
    if atyp == 1:
        host = str(ipaddress.IPv4Address(await reader.readexactly(4)))
    elif atyp == 3:
        length = (await reader.readexactly(1))[0]
        host = (await reader.readexactly(length)).decode("ascii", "replace")
    elif atyp == 4:
        host = str(ipaddress.IPv6Address(await reader.readexactly(16)))
    else:
        return command, None, None, REPLY_ATYP_UNSUPPORTED
    port = int.from_bytes(await reader.readexactly(2), "big")
    return command, host, port, REPLY_OK


def reply(code):
    return bytes([0x05, code, 0x00, 0x01, 0, 0, 0, 0, 0, 0])


async def pipe(reader, writer, router, upward):
    try:
        while True:
            chunk = await reader.read(BUFFER)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
            if upward:
                router.bytes_up += len(chunk)
            else:
                router.bytes_down += len(chunk)
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError, OSError, TimeoutError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(reader, writer, router):
    remote = None
    router.connections += 1
    router.active_now += 1
    try:
        greeting = await asyncio.wait_for(reader.readexactly(2), 10)
        if greeting[0] != 5:
            return
        await reader.readexactly(greeting[1])
        writer.write(b"\x05\x00")
        await writer.drain()

        command, host, port, status = await asyncio.wait_for(read_request_address(reader), 10)
        if status != REPLY_OK:
            writer.write(reply(status))
            await writer.drain()
            return
        if command != 1:
            writer.write(reply(REPLY_CMD_UNSUPPORTED))
            await writer.drain()
            return

        router.refresh()
        try:
            name, profile = config.resolve(router.cfg)
        except config.ConfigError as exc:
            router.failed += 1
            router.log("refused: " + str(exc))
            writer.write(reply(REPLY_NOT_ALLOWED))
            await writer.drain()
            return

        started = time.monotonic()
        try:
            remote_reader, remote_writer = await open_through(profile, host, port)
        except (UpstreamError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            router.failed += 1
            router.log("failed " + host + ":" + str(port) + " via " + name + " -> " + str(exc))
            writer.write(reply(REPLY_HOST_UNREACHABLE))
            await writer.drain()
            return

        remote = remote_writer
        took = int((time.monotonic() - started) * 1000)
        router.log("open  " + host + ":" + str(port) + " via " + name + " (" + str(took) + " ms)")

        writer.write(reply(REPLY_OK))
        await writer.drain()

        await asyncio.gather(
            pipe(reader, remote_writer, router, True),
            pipe(remote_reader, writer, router, False),
        )
        router.log("close " + host + ":" + str(port))
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError, OSError, ValueError):
        pass
    finally:
        router.active_now -= 1
        for target in (writer, remote):
            if target is None:
                continue
            try:
                target.close()
            except Exception:
                pass


async def create_server(router, host, port):
    kwargs = {}
    if os.name != "nt":
        kwargs["reuse_address"] = True
    server = await asyncio.start_server(lambda r, w: handle(r, w, router), host, int(port), **kwargs)
    router.listen = str(host) + ":" + str(port)
    return server


async def serve(host=None, port=None, verbose=True):
    router = Router(verbose=verbose)
    listen_host = host or router.cfg.get("listen_host", "127.0.0.1")
    listen_port = int(port or router.cfg.get("listen_port", 1080))

    server = await create_server(router, listen_host, listen_port)
    print("proxyswitch listening on socks5://" + listen_host + ":" + str(listen_port), flush=True)
    print("active profile: " + str(router.cfg.get("active")), flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError, ValueError):
            pass

    state_task = asyncio.create_task(router.state_loop())
    try:
        async with server:
            await stop.wait()
    except KeyboardInterrupt:
        pass
    state_task.cancel()
    clear_state()
    print("stopped", flush=True)


class ServerThread:
    def __init__(self, host=None, port=None, sink=None):
        self.host = host
        self.port = port
        self.sink = sink
        self.router = None
        self.error = None
        self.loop = None
        self.ready = threading.Event()
        self._stop = None
        self._thread = None

    def start(self, timeout=10.0):
        self.error = None
        self.ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.ready.wait(timeout)
        return self.error is None

    def is_running(self):
        return self._thread is not None and self._thread.is_alive() and self.error is None

    def stop(self, timeout=5.0):
        if self.loop is not None and self._stop is not None:
            try:
                self.loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        try:
            loop.run_until_complete(self._main())
        except Exception as exc:
            self.error = exc
            self.ready.set()
        finally:
            try:
                loop.close()
            except Exception:
                pass
            clear_state()

    async def _main(self):
        router = Router(verbose=False, sink=self.sink)
        self.router = router
        listen_host = self.host or router.cfg.get("listen_host", "127.0.0.1")
        listen_port = int(self.port or router.cfg.get("listen_port", 1080))
        try:
            server = await create_server(router, listen_host, listen_port)
        except OSError as exc:
            self.error = exc
            self.ready.set()
            return
        self._stop = asyncio.Event()
        self.ready.set()
        router.log("listening on socks5://" + listen_host + ":" + str(listen_port))
        state_task = asyncio.create_task(router.state_loop())
        async with server:
            await self._stop.wait()
        state_task.cancel()
        router.log("server stopped")
