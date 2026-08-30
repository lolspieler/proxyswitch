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

![the proxyswitch window](docs/screenshot.png)

---

## Install

You need Python 3.9 or newer, and Tk for the GUI. Tk ships with Python on Windows; on Linux it is usually a separate package.

### Linux

Install the dependencies for your distro:

```bash
sudo pacman -S python tk python-pipx          # Arch
sudo apt install python3 python3-tk pipx      # Debian / Ubuntu
sudo dnf install python3 python3-tkinter pipx # Fedora
```

Then clone and install:

```bash
git clone https://github.com/lolspieler/proxyswitch.git
cd proxyswitch
pipx ensurepath
./install.sh
```

`install.sh` checks that Tk is present, installs the package with pipx, and drops the desktop entry and icon into `~/.local/share/`, so the app shows up in your launcher (rofi, wofi, fuzzel, Noctalia, GNOME, whatever reads XDG entries). Open a new terminal afterwards so `~/.local/bin` is on your PATH, then:

```bash
proxyswitch-gui
```

If you'd rather do it by hand, or the script fails:

```bash
pipx install .
cp proxyswitch.desktop ~/.local/share/applications/
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp proxyswitch.svg ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications
```

Test that the launcher entry works without opening your launcher:

```bash
gtk-launch proxyswitch
```

### Windows

Install Python from [python.org](https://www.python.org/downloads/) — the installer includes Tk. Tick **Add python.exe to PATH** on the first screen, that part matters.

Then, in PowerShell:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

Close and reopen PowerShell so the PATH change takes effect, then:

```powershell
git clone https://github.com/lolspieler/proxyswitch.git
cd proxyswitch
pipx install .
```

Start it with `proxyswitch-gui`. That entry point is registered as a GUI script, so it opens without leaving a console window behind.

To get a Start menu or desktop shortcut, right-click `proxyswitch-gui.exe` in `%USERPROFILE%\.local\bin` and send it to your desktop. For autostart, press Win+R, type `shell:startup`, and drop the shortcut in that folder.

No git? Download the repo as a ZIP from the green **Code** button, extract it, and run the same `pipx install .` inside the extracted folder.

### As an AppImage

If you'd rather have one portable file than an install, build one:

```bash
cd ~/dev/proxyswitch
bash build-appimage.sh
```

It bundles the Python interpreter, the standard library and Tcl/Tk from your machine, so the result runs on systems that don't have Python or Tk installed at all. You need `python3`, `tk` and `curl` on the machine you build on. The script fetches `appimagetool` from GitHub if it isn't already installed.

Out comes `proxyswitch-x86_64.AppImage`, around 18 MB:

```bash
chmod +x proxyswitch-x86_64.AppImage
./proxyswitch-x86_64.AppImage
```

The CLI is in there too:

```bash
./proxyswitch-x86_64.AppImage --cli ls
./proxyswitch-x86_64.AppImage --cli use work
```

Move it wherever you like — `~/Applications` is the usual spot. To get it into your launcher, install [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher), or write the desktop entry yourself and point `Exec=` at the file's full path.

Two caveats. If the AppImage refuses to start with a FUSE error, either install `fuse2`, or run it with `APPIMAGE_EXTRACT_AND_RUN=1 ./proxyswitch-x86_64.AppImage`. And an AppImage built on Arch will generally run on older distros only if their glibc is new enough — build on the oldest system you care about if you plan to hand it around.

### Without installing anything

Both platforms can run it straight out of the folder:

```bash
python3 -m proxyswitch gui      # Linux
py -m proxyswitch gui           # Windows
```

On Windows, double-clicking `launch-gui.pyw` does the same thing.

### Where your settings live

- Linux: `~/.config/proxyswitch/config.json`
- Windows: `%APPDATA%\proxyswitch\config.json`

On Linux the file is chmod 600, because proxy passwords sit in it in plain text. It's in `.gitignore` — keep it that way.

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
docs/
  screenshot.png
install.sh      one-shot installer for Linux
build-appimage.sh  packs everything into a portable AppImage
launch-gui.pyw  double-click launcher for Windows
```

If you want to extend it: per-destination rules (split tunnelling) go into `server.handle`, right before `config.resolve` picks the profile. Rotating proxies go in the same spot.

---

BTW that README.md has been slightly improved by ai and spelling mistakes have also been fixxt with AI

## License

MIT. See [LICENSE](LICENSE).
