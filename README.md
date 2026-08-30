# proxyswitch

A small desktop app that runs a SOCKS5 proxy on your own machine and forwards everything through whichever upstream proxy you pick — SOCKS5, HTTP CONNECT, or no proxy at all.

The point is that you configure your browser or your tools exactly once, pointing them at `127.0.0.1:1080`. After that you switch proxies from the app window and nothing else has to change. No restarting the browser, no editing config files, no restarting the proxy itself.

```
Firefox / curl / whatever
        |   socks5://127.0.0.1:1080
        v
   proxyswitch  ->  active profile  ->  the internet
                    (socks5 / http / direct)
```

There's a GUI and a CLI. Both talk to the same config file, so you can start the server from the app and flip profiles from a keybind, or the other way round.

No third-party packages. Everything is standard library. Runs on Windows, Debian/Ubuntu and Arch.

---

## Install

You need Python 3.9 or newer and Tk for the GUI. Tk usually ships with Python on Windows and macOS, but on Linux it's often a separate package.

### Debian / Ubuntu

```bash
sudo apt install python3 python3-tk python3-venv pipx
pipx ensurepath
```

### Arch

```bash
sudo pacman -S python tk python-pipx
pipx ensurepath
```

### Windows

Install Python from python.org (the installer includes Tk) and tick "Add python.exe to PATH". Then, in PowerShell:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

### Then, on any of them

```bash
cd proxyswitch
pipx install .
```

That gives you two commands: `proxyswitch` for the terminal and `proxyswitch-gui` for the app. On Windows the GUI one starts without a console window hanging around.

If you don't want to install anything, running it straight out of the folder works too:

```bash
python3 -m proxyswitch gui
```

On Windows you can also just double-click `launch-gui.pyw`.

Your profiles live in:

- Linux: `~/.config/proxyswitch/config.json`
- Windows: `%APPDATA%\proxyswitch\config.json`

The file is chmod 600 on Linux because proxy passwords are in there in plain text. Don't commit it.

---

## Using the app

Start it with `proxyswitch-gui`, or `proxyswitch gui` if you'd rather type it.

It's one small window, roughly top to bottom in the order you'd use it.

**Listen on** is the address and port the local proxy binds to. `127.0.0.1` and `1080` are fine for almost everyone. The two fields grey out while the server is running, since moving the listener mid-flight would just drop everything.

**Profile** is the dropdown of upstreams you've added. **Traffic** below it is the actual switch: *through profile* sends everything to the selected proxy, *direct, no proxy* keeps the local listener up but sends traffic straight out. That second option is the one you want when a site blocks your proxy and you just need it to work for a minute. The small grey line underneath tells you what the selected profile actually is, so you can see at a glance whether you're on the SOCKS5 box at home or the company HTTP proxy.

Switching takes effect immediately, even with the server running. New connections take the new path, connections that are already open finish on the old one, so a download in progress doesn't get killed.

**Start** and **Stop** control the listener. When it's up, the line below turns green and you get the URL plus a counter: how many connections, how many are open right now, how many failed, and bytes each way.

**Add / Edit / Delete** manage profiles, always acting on whatever is selected in the dropdown. **Test** opens a connection through the selected profile, times it, and fetches your exit IP, so you know it's alive and where it comes out before you rely on it. The result appears in the grey line underneath.

**WireGuard** lists the tunnels it found on your machine, with Up, Down and Status. It's a wrapper around `wg-quick`, see further down.

**Copy proxy URL** puts `socks5h://127.0.0.1:1080` on the clipboard, which is the form most tools want. **show log** unfolds a pane at the bottom with every connection and every failure including the reason. Handy when a proxy misbehaves, out of the way when it doesn't.

Everything you do in the window is written to the same config file the CLI uses, and vice versa. Change the active profile from a keybind and the open window follows within a second.

---

## Using it from the terminal

```bash
proxyswitch add home --kind socks5 --host 10.0.0.5 --port 1080
proxyswitch add work --kind http --host proxy.company.com --port 3128 --username noah
proxyswitch add direct --kind direct

proxyswitch use home
proxyswitch run
```

| Command | What it does |
| --- | --- |
| `add <name> --kind socks5\|http\|direct --host H --port P [--username U] [--password P] [--note ...]` | Create a profile. Leave off `--password` and it prompts instead of putting it in your shell history |
| `import <file> [--prefix name]` | Bulk import from a list of proxy URIs, one per line |
| `ls` | List profiles, active one marked |
| `use <name>` | Switch the active profile |
| `rm <name>` | Delete a profile |
| `test [name] [--all] [--fast] [--switch]` | Latency and exit IP. `--fast` skips the IP lookup, `--switch` jumps to the fastest one |
| `run [--host H] [--port P] [--quiet]` | Start the server in the foreground |
| `gui` | Open the app |
| `status` | Is it running, for how long, how much traffic |
| `listen --host H --port P` | Change the listen address permanently |
| `vpn ls\|up <name>\|down <name>\|status` | WireGuard tunnels |

The import format:

```
socks5://10.0.0.5:1080#home
socks5://user:password@proxy.example.net:1080#provider-de
http://noah:secret@proxy.company.com:3128#work
```

Whatever follows `#` becomes the profile name. Leave it off and you get `proxy1`, `proxy2` and so on.

What `test` looks like:

```
ok   provider-de   84 ms  exit 185.x.x.x
ok   provider-nl  121 ms  exit 45.x.x.x
tot  work          upstream rejected the credentials
```

---

## Pointing things at it

**curl**

```bash
curl --proxy socks5h://127.0.0.1:1080 https://api.ipify.org
```

The `h` matters. Without it curl resolves DNS locally, which leaks the hostname you're visiting to your ISP even though the traffic itself goes through the proxy.

**Firefox**: Settings, Network Settings, Manual proxy configuration. SOCKS host `127.0.0.1`, port `1080`, SOCKS v5, and tick "Proxy DNS when using SOCKS v5".

**Chrome / Chromium / Edge**: they take it as a launch flag.

```bash
chromium --proxy-server="socks5://127.0.0.1:1080"
```

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --proxy-server="socks5://127.0.0.1:1080"
```

**Command-line tools on Linux**: most of them read the environment.

```bash
export ALL_PROXY=socks5h://127.0.0.1:1080
export HTTP_PROXY=socks5h://127.0.0.1:1080
export HTTPS_PROXY=socks5h://127.0.0.1:1080
export NO_PROXY=localhost,127.0.0.1,::1,192.168.0.0/16
```

**Programs that don't do proxies at all**: on Debian/Ubuntu and Arch there's `proxychains-ng` (`apt install proxychains4` / `pacman -S proxychains-ng`). Put `socks5 127.0.0.1 1080` at the bottom of the config and run `proxychains -q yourprogram`. On Windows the equivalent is Proxifier, which is commercial, or you use per-app settings.

**Windows system proxy**: the Settings page under Network, Proxy only really handles HTTP, not SOCKS. Per-app is the saner route on Windows. If you want everything tunnelled, use a VPN instead.

---

## Autostart

**Linux (systemd user service)**

```bash
cp proxyswitch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now proxyswitch
journalctl --user -u proxyswitch -f
```

Drop `proxyswitch.desktop` into `~/.local/share/applications/` and the app shows up in your launcher.

If you're on Hyprland, binding the switch to a key is nice:

```
bind = SUPER SHIFT, P, exec, proxyswitch use home && notify-send "Proxy" "home"
bind = SUPER SHIFT, O, exec, proxyswitch use direct && notify-send "Proxy" "direct"
```

The app also writes `state.json` next to the config every second, with the active profile, open connections and traffic counters. That's an easy source for a status bar module.

**Windows**

Press Win+R, type `shell:startup`, and drop a shortcut in there pointing at `proxyswitch-gui.exe` (it's in `%USERPROFILE%\.local\bin` after a pipx install) or at `launch-gui.pyw`.

For a headless background service, Task Scheduler with "At log on" and `pythonw -m proxyswitch run --quiet` works fine.

---

## What it does and doesn't do

It handles SOCKS5 `CONNECT` with IPv4, IPv6 and hostnames. Hostnames go to the upstream unresolved, so with a SOCKS5 upstream there's no DNS leak. Upstream authentication works for both SOCKS5 username/password (RFC 1929) and HTTP Basic.

It does not implement UDP `ASSOCIATE` or `BIND`. In practice that means QUIC/HTTP3 and most games won't go through it — browsers detect the SOCKS proxy and fall back to TCP on their own, so web browsing is unaffected. If you need UDP, you need a VPN, not a proxy.

There's no authentication on the local listener either, which is why it binds to `127.0.0.1` by default. If you change that to `0.0.0.0`, anyone who can reach your machine can use your proxy. Only do that behind a firewall you trust.

---

## Proxy or VPN?

A proxy here is per-application. Only the programs you point at `127.0.0.1:1080` go through it — package updates, NTP, background services and everything else keep going out the normal way. That's often exactly what you want.

A VPN like WireGuard works at the interface level and takes the whole machine with it. The two combine fine: WireGuard as the baseline, proxyswitch for the handful of programs that should come out somewhere else.

The WireGuard part of this app is a thin wrapper, nothing clever:

```bash
sudo apt install wireguard-tools
sudo pacman -S wireguard-tools

proxyswitch vpn ls
proxyswitch vpn up mullvad-de
proxyswitch vpn status
proxyswitch vpn down mullvad-de
```

It reads `.conf` files from `/etc/wireguard` on Linux and from the WireGuard data directory on Windows, and you can override that with `PROXYSWITCH_WG_DIR`.

`up` and `down` call `sudo wg-quick`, so you get a password prompt. To skip that, add a sudoers rule in `/etc/sudoers.d/wg`:

```
yourname ALL=(root) NOPASSWD: /usr/bin/wg-quick
```

On Windows it drives `wireguard.exe /installtunnelservice`, which needs an administrator prompt.

A kill switch belongs in the WireGuard config itself, as `PostUp`/`PreDown` firewall rules, not in this app.

---

## Things worth knowing

A proxy doesn't encrypt anything. Whoever runs it sees where you're connecting to, and for plain HTTP they see the contents too. TLS is still doing all the work.

`test` fetches your exit IP over plain HTTP from `api.ipify.org`, deliberately, so the tool doesn't need to do a TLS handshake. The upstream sees that request. Use `--fast` if you'd rather it didn't happen.

Browsers can leak your real IP through WebRTC regardless of what the proxy is doing. In Firefox that's `media.peerconnection.enabled` in `about:config`, if it matters to you.

---

## Layout

```
proxyswitch/
  config.py     loading, saving and resolving profiles
  upstream.py   SOCKS5 client handshake and HTTP CONNECT
  server.py     the local SOCKS5 server, routing, stats, thread runner
  health.py     latency and exit IP checks
  vpn.py        wireguard wrapper
  gui.py        the Tk app
  cli.py        argument parsing and terminal output
```

If you want to extend it: per-destination rules (split tunnelling) go into `server.handle`, right before `config.resolve` picks the profile. Rotating proxies go in the same spot.
