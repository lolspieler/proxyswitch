import asyncio
import base64
import ipaddress

SOCKS5_ERRORS = {
    1: "general upstream proxy failure",
    2: "connection not allowed by ruleset",
    3: "network unreachable",
    4: "host unreachable",
    5: "connection refused",
    6: "TTL expired",
    7: "command not supported",
    8: "address type not supported",
}


class UpstreamError(Exception):
    pass


def encode_address(host, port):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            raw = host.encode("ascii")
        except UnicodeEncodeError:
            raw = host.encode("idna")
        if len(raw) > 255:
            raise UpstreamError("hostname too long")
        return b"\x03" + bytes([len(raw)]) + raw + port.to_bytes(2, "big")
    if ip.version == 4:
        return b"\x01" + ip.packed + port.to_bytes(2, "big")
    return b"\x04" + ip.packed + port.to_bytes(2, "big")


async def open_through(profile, host, port, timeout=15.0):
    kind = profile.get("kind", "socks5")
    if kind == "direct":
        return await asyncio.wait_for(asyncio.open_connection(host, port), timeout)

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(profile["host"], int(profile["port"])), timeout
    )
    try:
        if kind == "socks5":
            await asyncio.wait_for(_socks5_client(reader, writer, profile, host, port), timeout)
        elif kind == "http":
            await asyncio.wait_for(_http_connect(reader, writer, profile, host, port), timeout)
        else:
            raise UpstreamError("unknown profile type: " + str(kind))
    except BaseException:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        raise
    return reader, writer


async def _socks5_client(reader, writer, profile, host, port):
    username = profile.get("username")
    password = profile.get("password", "")

    if username:
        writer.write(b"\x05\x02\x00\x02")
    else:
        writer.write(b"\x05\x01\x00")
    await writer.drain()

    version, method = await reader.readexactly(2)
    if version != 5:
        raise UpstreamError("upstream does not speak SOCKS5")
    if method == 0x02:
        if not username:
            raise UpstreamError("upstream requires a username and password")
        user_raw = username.encode("utf-8")
        pass_raw = (password or "").encode("utf-8")
        writer.write(b"\x01" + bytes([len(user_raw)]) + user_raw + bytes([len(pass_raw)]) + pass_raw)
        await writer.drain()
        _, status = await reader.readexactly(2)
        if status != 0:
            raise UpstreamError("upstream rejected the credentials")
    elif method != 0x00:
        raise UpstreamError("no supported auth method (0x%02x)" % method)

    writer.write(b"\x05\x01\x00" + encode_address(host, port))
    await writer.drain()

    head = await reader.readexactly(4)
    if head[1] != 0:
        raise UpstreamError(SOCKS5_ERRORS.get(head[1], "SOCKS5 error 0x%02x" % head[1]))
    atyp = head[3]
    if atyp == 1:
        await reader.readexactly(4)
    elif atyp == 3:
        length = (await reader.readexactly(1))[0]
        await reader.readexactly(length)
    elif atyp == 4:
        await reader.readexactly(16)
    else:
        raise UpstreamError("unknown address type in reply")
    await reader.readexactly(2)


async def _http_connect(reader, writer, profile, host, port):
    target = "[" + host + "]:" + str(port) if ":" in host else host + ":" + str(port)
    lines = ["CONNECT " + target + " HTTP/1.1", "Host: " + target, "Proxy-Connection: keep-alive"]
    if profile.get("username"):
        token = profile["username"] + ":" + profile.get("password", "")
        lines.append("Proxy-Authorization: Basic " + base64.b64encode(token.encode("utf-8")).decode("ascii"))
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
    await writer.drain()

    header = await reader.readuntil(b"\r\n\r\n")
    status_line = header.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].startswith("2"):
        raise UpstreamError("upstream replied: " + status_line)
