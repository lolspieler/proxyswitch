import asyncio
import time

from .upstream import UpstreamError, open_through

DEFAULT_PROBE_HOST = "api.ipify.org"
DEFAULT_PROBE_PORT = 80


async def latency(profile, host="1.1.1.1", port=443, timeout=8.0):
    started = time.monotonic()
    reader, writer = await open_through(profile, host, port, timeout=timeout)
    elapsed = (time.monotonic() - started) * 1000
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return elapsed


async def exit_ip(profile, host=DEFAULT_PROBE_HOST, port=DEFAULT_PROBE_PORT, timeout=10.0):
    reader, writer = await open_through(profile, host, port, timeout=timeout)
    try:
        request = "GET / HTTP/1.1\r\nHost: " + host + "\r\nUser-Agent: proxyswitch\r\nConnection: close\r\n\r\n"
        writer.write(request.encode("ascii"))
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(-1), timeout)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    parts = raw.split(b"\r\n\r\n", 1)
    if len(parts) != 2:
        raise UpstreamError("unreadable response from probe endpoint")
    body = parts[1].decode("utf-8", "replace").strip()
    first = body.splitlines()[0].strip() if body else ""
    if not first:
        raise UpstreamError("empty response from probe endpoint")
    return first[:64]


async def check(profile, want_ip=True):
    result = {"ok": False, "ms": None, "ip": None, "error": None}
    try:
        result["ms"] = await latency(profile)
        if want_ip:
            result["ip"] = await exit_ip(profile)
        result["ok"] = True
    except (UpstreamError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        result["error"] = str(exc) or exc.__class__.__name__
    return result


async def check_many(profiles, want_ip=True, parallel=8):
    gate = asyncio.Semaphore(parallel)

    async def run(name, profile):
        async with gate:
            return name, await check(profile, want_ip=want_ip)

    tasks = [run(name, profile) for name, profile in profiles]
    return await asyncio.gather(*tasks)
