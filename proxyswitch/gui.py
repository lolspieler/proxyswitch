import asyncio
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

from . import config, health, server, vpn

APP_TITLE = "proxyswitch"
POLL_MS = 700
DIRECT = "direct"
LOG_LIMIT = 300
SMALL = ("TkDefaultFont", 8)
KIND_LABELS = {"socks5": "SOCKS5", "http": "HTTP CONNECT", "direct": "direct"}


def human(value):
    step = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if step < 1024 or unit == "TB":
            return ("%.1f " % step) + unit
        step /= 1024
    return str(value)


def separator(parent, pady=9):
    line = tk.Frame(parent, height=2, bd=1, relief="sunken")
    line.pack(fill="x", pady=pady)
    return line


def hint(parent, text):
    return tk.Label(parent, text=text, fg="gray40", font=SMALL)


class ProfileDialog(tk.Toplevel):
    def __init__(self, master, title, initial=None, name=""):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        initial = initial or {}

        body = tk.Frame(self, padx=14, pady=12)
        body.pack(fill="both", expand=True)

        self.var_name = tk.StringVar(value=name)
        self.var_kind = tk.StringVar(value=initial.get("kind", "socks5"))
        self.var_host = tk.StringVar(value=str(initial.get("host", "")))
        self.var_port = tk.StringVar(value=str(initial.get("port", "")))
        self.var_user = tk.StringVar(value=initial.get("username", ""))
        self.var_pass = tk.StringVar(value=initial.get("password", ""))
        self.var_note = tk.StringVar(value=initial.get("note", ""))

        tk.Label(body, text="Name", anchor="w").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 10))
        tk.Entry(body, textvariable=self.var_name, width=24).grid(row=0, column=1, sticky="w", pady=3)

        tk.Label(body, text="Type", anchor="w").grid(row=1, column=0, sticky="nw", pady=3, padx=(0, 10))
        kinds = tk.Frame(body)
        kinds.grid(row=1, column=1, sticky="w", pady=3)
        for kind in config.VALID_KINDS:
            tk.Radiobutton(kinds, text=KIND_LABELS.get(kind, kind), variable=self.var_kind, value=kind, command=self.sync_fields).pack(anchor="w")

        rows = [
            ("Host", self.var_host, None),
            ("Port", self.var_port, None),
            ("Username", self.var_user, None),
            ("Password", self.var_pass, "*"),
            ("Note", self.var_note, None),
        ]
        self.entries = {}
        for index, (label, variable, secret) in enumerate(rows, start=2):
            tk.Label(body, text=label, anchor="w").grid(row=index, column=0, sticky="w", pady=3, padx=(0, 10))
            entry = tk.Entry(body, textvariable=variable, width=24)
            if secret:
                entry.configure(show=secret)
            entry.grid(row=index, column=1, sticky="w", pady=3)
            self.entries[label] = entry

        hint(body, "leave username empty if the proxy needs no login").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        buttons = tk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(12, 0))
        tk.Button(buttons, text="Cancel", width=8, command=self.destroy).pack(side="right", padx=(6, 0))
        tk.Button(buttons, text="Save", width=8, command=self.on_save).pack(side="right")

        self.sync_fields()
        self.bind("<Return>", lambda event: self.on_save())
        self.bind("<Escape>", lambda event: self.destroy())
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def sync_fields(self):
        state = "disabled" if self.var_kind.get() == "direct" else "normal"
        for label in ("Host", "Port", "Username", "Password"):
            self.entries[label].configure(state=state)

    def on_save(self):
        name = self.var_name.get().strip()
        kind = self.var_kind.get()
        if not name:
            messagebox.showerror(APP_TITLE, "The profile needs a name.", parent=self)
            return
        profile = {"kind": kind}
        if kind != "direct":
            host = self.var_host.get().strip()
            port = self.var_port.get().strip()
            if not host or not port.isdigit():
                messagebox.showerror(APP_TITLE, "Host and a numeric port are required.", parent=self)
                return
            profile["host"] = host
            profile["port"] = int(port)
            user = self.var_user.get().strip()
            if user:
                profile["username"] = user
                profile["password"] = self.var_pass.get()
        note = self.var_note.get().strip()
        if note:
            profile["note"] = note
        self.result = (name, profile)
        self.destroy()


class App(tk.Frame):
    def __init__(self, master):
        super().__init__(master, padx=12, pady=10)
        self.pack(fill="both", expand=True)

        self.cfg = config.load()
        self.stamp = config.mtime()
        self.thread = None
        self.events = queue.Queue()
        self.log_lines = []

        self.var_host = tk.StringVar(value=str(self.cfg.get("listen_host", "127.0.0.1")))
        self.var_port = tk.StringVar(value=str(self.cfg.get("listen_port", 1080)))
        self.var_profile = tk.StringVar(value="")
        self.var_route = tk.StringVar(value=DIRECT if self.cfg.get("active") == DIRECT else "profile")
        self.var_tunnel = tk.StringVar(value="")
        self.var_showlog = tk.IntVar(value=0)

        self.build_listen()
        self.build_upstream()
        separator(self)
        self.build_controls()
        separator(self)
        self.build_profile_buttons()
        separator(self)
        self.build_vpn()
        separator(self)
        self.build_footer()

        self.refresh_profiles()
        self.refresh_tunnels()
        self.update_status()
        self.poll()
        master.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_listen(self):
        tk.Label(self, text="Listen on", anchor="w").pack(fill="x")
        row = tk.Frame(self)
        row.pack(fill="x", pady=(3, 0))
        self.host_entry = tk.Entry(row, textvariable=self.var_host, width=13, justify="center")
        self.host_entry.grid(row=0, column=0)
        self.port_entry = tk.Entry(row, textvariable=self.var_port, width=6, justify="center")
        self.port_entry.grid(row=0, column=1, padx=(8, 0))
        hint(row, "address").grid(row=1, column=0)
        hint(row, "port").grid(row=1, column=1, padx=(8, 0))

    def build_upstream(self):
        block = tk.Frame(self)
        block.pack(fill="x", pady=(10, 0))
        block.columnconfigure(1, weight=1)

        tk.Label(block, text="Profile", anchor="w").grid(row=0, column=0, sticky="w", pady=2, padx=(0, 8))
        self.profile_menu = tk.OptionMenu(block, self.var_profile, "")
        self.profile_menu.configure(width=14, anchor="w")
        self.profile_menu.grid(row=0, column=1, sticky="w", pady=2)

        tk.Label(block, text="Traffic", anchor="w").grid(row=1, column=0, sticky="nw", pady=2, padx=(0, 8))
        radios = tk.Frame(block)
        radios.grid(row=1, column=1, sticky="w", pady=2)
        tk.Radiobutton(radios, text="through profile", variable=self.var_route, value="profile", command=self.apply_route).pack(anchor="w")
        tk.Radiobutton(radios, text="direct, no proxy", variable=self.var_route, value=DIRECT, command=self.apply_route).pack(anchor="w")

        self.info_label = hint(self, "")
        self.info_label.pack(fill="x", pady=(6, 0))

    def build_controls(self):
        row = tk.Frame(self)
        row.pack(fill="x")
        self.start_button = tk.Button(row, text="Start", width=10, command=self.start_server)
        self.start_button.pack(side="left")
        self.stop_button = tk.Button(row, text="Stop", width=10, state="disabled", command=self.stop_server)
        self.stop_button.pack(side="right")

        self.status_label = tk.Label(self, text="stopped", fg="gray30")
        self.status_label.pack(pady=(9, 0))
        self.url_label = hint(self, "")
        self.url_label.pack()
        self.traffic_label = hint(self, "")
        self.traffic_label.pack()

    def build_profile_buttons(self):
        row = tk.Frame(self)
        row.pack(fill="x")
        for text, command in (("Add", self.on_add), ("Edit", self.on_edit), ("Delete", self.on_delete), ("Test", self.on_test)):
            tk.Button(row, text=text, width=6, command=command).pack(side="left", expand=True, fill="x", padx=1)
        self.test_label = hint(self, "no test yet")
        self.test_label.pack(pady=(5, 0))

    def build_vpn(self):
        row = tk.Frame(self)
        row.pack(fill="x")
        tk.Label(row, text="WireGuard", anchor="w").pack(side="left", padx=(0, 8))
        self.tunnel_menu = tk.OptionMenu(row, self.var_tunnel, "")
        self.tunnel_menu.configure(width=12, anchor="w")
        self.tunnel_menu.pack(side="left")

        row2 = tk.Frame(self)
        row2.pack(fill="x", pady=(5, 0))
        for text, command in (("Up", lambda: self.on_vpn(vpn.up)), ("Down", lambda: self.on_vpn(vpn.down)), ("Status", lambda: self.on_vpn(None))):
            tk.Button(row2, text=text, width=6, command=command).pack(side="left", expand=True, fill="x", padx=1)

    def build_footer(self):
        row = tk.Frame(self)
        row.pack(fill="x")
        tk.Button(row, text="Copy proxy URL", command=self.copy_url).pack(side="left")
        tk.Checkbutton(row, text="show log", variable=self.var_showlog, command=self.toggle_log).pack(side="right")

        self.log_frame = tk.Frame(self)
        self.log = tk.Text(self.log_frame, height=8, width=38, wrap="none", state="disabled", relief="sunken", bd=1, font=SMALL)
        self.log.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(self.log_frame, orient="vertical", command=self.log.yview)
        scroll.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scroll.set)

    def toggle_log(self):
        if self.var_showlog.get():
            self.log_frame.pack(fill="both", expand=True, pady=(8, 0))
        else:
            self.log_frame.pack_forget()
        self.winfo_toplevel().geometry("")

    def append_log(self, message):
        self.log_lines.append(time.strftime("[%H:%M:%S] ") + message)
        if len(self.log_lines) > LOG_LIMIT:
            del self.log_lines[:-LOG_LIMIT]
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", "\n".join(self.log_lines))
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh_profiles(self, keep=None):
        names = sorted(self.cfg["profiles"])
        menu = self.profile_menu["menu"]
        menu.delete(0, "end")
        for name in names:
            menu.add_command(label=name, command=lambda value=name: self.pick_profile(value))
        wanted = keep or self.var_profile.get()
        active = self.cfg.get("active")
        if wanted not in names:
            wanted = active if active in names else (names[0] if names else "")
        self.var_profile.set(wanted or "no profiles yet")
        self.profile_menu.configure(state="normal" if names else "disabled")
        self.var_route.set(DIRECT if active == DIRECT else "profile")
        self.update_info()

    def refresh_tunnels(self):
        names = vpn.available()
        menu = self.tunnel_menu["menu"]
        menu.delete(0, "end")
        for name in names:
            menu.add_command(label=name, command=lambda value=name: self.var_tunnel.set(value))
        self.var_tunnel.set(names[0] if names else "none found")
        self.tunnel_menu.configure(state="normal" if names else "disabled")

    def current_profile(self):
        name = self.var_profile.get()
        return name if name in self.cfg["profiles"] else None

    def update_info(self):
        if self.var_route.get() == DIRECT:
            self.info_label.configure(text="upstream bypassed, traffic leaves from this machine")
            return
        name = self.current_profile()
        if name is None:
            self.info_label.configure(text="add a profile to route traffic through a proxy")
            return
        profile = self.cfg["profiles"][name]
        kind = profile.get("kind", "socks5")
        text = KIND_LABELS.get(kind, kind)
        if kind != "direct":
            text += "  " + str(profile.get("host")) + ":" + str(profile.get("port"))
            if profile.get("username"):
                text += "  (login)"
        if profile.get("note"):
            text += "  " + profile["note"]
        self.info_label.configure(text=text)

    def pick_profile(self, name):
        self.var_profile.set(name)
        if self.var_route.get() != DIRECT:
            self.set_active(name)
        self.update_info()

    def apply_route(self):
        if self.var_route.get() == DIRECT:
            self.set_active(DIRECT)
        else:
            name = self.current_profile()
            if name is None:
                self.var_route.set(DIRECT)
                messagebox.showinfo(APP_TITLE, "There is no profile yet. Add one first.")
                return
            self.set_active(name)
        self.update_info()

    def set_active(self, name):
        cfg = config.load()
        cfg["active"] = name
        config.save(cfg)
        self.cfg = cfg
        self.stamp = config.mtime()
        self.append_log("active upstream is now " + name)

    def start_server(self):
        host = self.var_host.get().strip() or "127.0.0.1"
        port = self.var_port.get().strip()
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            messagebox.showerror(APP_TITLE, "Port must be a number between 1 and 65535.")
            return
        cfg = config.load()
        cfg["listen_host"] = host
        cfg["listen_port"] = int(port)
        config.save(cfg)
        self.cfg = cfg
        self.stamp = config.mtime()

        handle = server.ServerThread(host, int(port), sink=self.events.put)
        if not handle.start() or handle.error is not None:
            messagebox.showerror(APP_TITLE, "Could not start the server:\n\n" + str(handle.error))
            handle.stop()
            return
        self.thread = handle
        self.update_status()

    def stop_server(self):
        if self.thread is not None:
            self.thread.stop()
            self.thread = None
            self.append_log("server stopped")
        self.update_status()

    def is_running(self):
        return self.thread is not None and self.thread.is_running()

    def update_status(self):
        running = self.is_running()
        url = "socks5://" + str(self.cfg.get("listen_host")) + ":" + str(self.cfg.get("listen_port"))
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.host_entry.configure(state="disabled" if running else "normal")
        self.port_entry.configure(state="disabled" if running else "normal")
        if not running:
            self.status_label.configure(text="stopped", fg="gray30")
            self.url_label.configure(text="not accepting connections")
            self.traffic_label.configure(text="")
            return
        self.status_label.configure(text="running", fg="dark green")
        self.url_label.configure(text=url)
        router = self.thread.router
        if router is None:
            return
        uptime = int(time.time() - router.started)
        self.traffic_label.configure(
            text=str(router.connections) + " conns, " + str(router.active_now) + " open, " + str(router.failed)
            + " failed   up " + human(router.bytes_up) + " down " + human(router.bytes_down)
            + "   " + str(uptime // 60) + "m"
        )

    def copy_url(self):
        url = "socks5h://" + str(self.cfg.get("listen_host")) + ":" + str(self.cfg.get("listen_port"))
        self.clipboard_clear()
        self.clipboard_append(url)
        self.append_log("copied " + url)
        self.test_label.configure(text="copied " + url)

    def on_add(self):
        dialog = ProfileDialog(self.winfo_toplevel(), "New profile")
        self.wait_window(dialog)
        if dialog.result is None:
            return
        name, profile = dialog.result
        cfg = config.load()
        cfg["profiles"][name] = profile
        if cfg.get("active") is None:
            cfg["active"] = name
        config.save(cfg)
        self.cfg = cfg
        self.stamp = config.mtime()
        self.append_log("added profile " + name)
        self.refresh_profiles(keep=name)

    def on_edit(self):
        name = self.current_profile()
        if name is None:
            return
        dialog = ProfileDialog(self.winfo_toplevel(), "Edit profile", self.cfg["profiles"].get(name), name)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        new_name, profile = dialog.result
        cfg = config.load()
        if new_name != name:
            cfg["profiles"].pop(name, None)
            if cfg.get("active") == name:
                cfg["active"] = new_name
        cfg["profiles"][new_name] = profile
        config.save(cfg)
        self.cfg = cfg
        self.stamp = config.mtime()
        self.append_log("saved profile " + new_name)
        self.refresh_profiles(keep=new_name)

    def on_delete(self):
        name = self.current_profile()
        if name is None:
            return
        if not messagebox.askyesno(APP_TITLE, "Delete profile " + name + "?"):
            return
        cfg = config.load()
        config.remove_profile(cfg, name)
        config.save(cfg)
        self.cfg = cfg
        self.stamp = config.mtime()
        self.append_log("deleted profile " + name)
        self.refresh_profiles()

    def on_test(self):
        if self.var_route.get() == DIRECT:
            target = (DIRECT, {"kind": "direct"})
        else:
            name = self.current_profile()
            if name is None:
                return
            target = (name, self.cfg["profiles"][name])
        self.test_label.configure(text="testing " + target[0] + " ...")
        threading.Thread(target=self.run_test, args=(target,), daemon=True).start()

    def run_test(self, target):
        name, profile = target
        try:
            result = asyncio.run(health.check(profile))
        except Exception as exc:
            self.events.put(("test", name + ": " + str(exc)))
            return
        if result["ok"]:
            text = name + ": " + str(round(result["ms"])) + " ms"
            if result["ip"]:
                text += ", exit " + result["ip"]
        else:
            text = name + " failed: " + str(result["error"])
        self.events.put(("test", text))

    def on_vpn(self, action):
        name = self.var_tunnel.get()
        try:
            if action is None:
                output = vpn.status() or "no active tunnel"
                messagebox.showinfo(APP_TITLE, output)
                return
            if name not in vpn.available():
                messagebox.showinfo(APP_TITLE, "No tunnel selected.")
                return
            action(name)
            self.append_log("wireguard " + name + " " + ("up" if action is vpn.up else "down"))
            self.test_label.configure(text="wireguard " + name + " " + ("up" if action is vpn.up else "down"))
        except vpn.VpnError as exc:
            messagebox.showerror(APP_TITLE, str(exc))

    def poll(self):
        while True:
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple):
                self.test_label.configure(text=item[1])
                self.append_log(item[1])
            else:
                self.append_log(str(item))

        stamp = config.mtime()
        if stamp != self.stamp:
            self.stamp = stamp
            self.cfg = config.load()
            self.refresh_profiles()
            self.append_log("config changed on disk, reloaded")
        self.update_status()
        self.after(POLL_MS, self.poll)

    def on_close(self):
        if self.thread is not None:
            self.thread.stop()
        self.winfo_toplevel().destroy()


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.resizable(False, False)
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
