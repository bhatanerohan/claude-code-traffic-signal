"""Claude Code traffic-signal overlay.

A small always-on-top traffic light that mirrors what Claude Code is doing.
Hooks in ~/.claude/settings.json write a single word into state.txt; this
process polls that file and lights the matching lamp.

    yellow            - Claude is working, or a background task is still running
    red    (blinking) - Claude needs a permission or a decision from you
    green             - task done / idle

Drag with the left mouse button. Right-click for the menu.
"""

import json
import math
import os
import re
import socket
import tempfile
import threading
import time
import tkinter as tk

BASE = os.path.join(os.path.expanduser("~"), ".claude", "signal")
STATE_FILE = os.path.join(BASE, "state.txt")
CONFIG_FILE = os.path.join(BASE, "overlay-config.json")
LOCK_PORT = 53121  # bound to 127.0.0.1 to keep a single overlay running

# Background tasks write their output here, and Claude Code appends an exit
# marker when one ends. No hook fires on background completion, so these files
# are the only available signal.
TASKS_ROOT = os.path.join(tempfile.gettempdir(), "claude")
# A finished task ends with a bracketed sentinel. It is NOT always an exit code:
# a killed task ends with "[killed]", and treating that as still-running was what
# pinned the light yellow (18 of 121 files here ended that way).
DONE_RE = re.compile(
    rb"\[(?:exited with code -?\d+|killed|terminated[^\]]*|timed out[^\]]*)\]\s*\Z"
)
BG_WINDOW = 600  # an output file untouched for longer than this counts as dead
BG_SCAN_EVERY = 2.0
BG_DISCOVER_EVERY = 30.0  # how often to re-hunt for task directories

W, H = 54, 140
LAMP_X = 27
LAMP_Y = (26, 70, 114)
LAMP_R = 16

KEY = "#ff00fe"  # transparent-color key; nothing else may use it
BODY = "#1c1c1e"
EDGE = "#48484a"

LAMPS = {
    "red": {"on": "#ff453a", "off": "#3d1512", "ring": "#ff9a93"},
    "yellow": {"on": "#ffd60a", "off": "#3d3208", "ring": "#ffe98a"},
    "green": {"on": "#32d74b", "off": "#123d1a", "ring": "#9af0a8"},
}
ORDER = ("red", "yellow", "green")

# state word (written by the hooks) -> lamp, animation
STATES = {
    "attention": ("red", "blink"),
    "working": ("yellow", "steady"),
    "done": ("green", "steady"),
    "idle": ("green", "steady"),
}
DEFAULT_STATE = "idle"
IDLE_STATES = ("done", "idle")  # states that a running background task overrides


def blend(c1, c2, t):
    """Linear blend between two #rrggbb colors, t in [0, 1]."""
    a = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i : i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_config(**kw):
    cfg = load_config()
    cfg.update(kw)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


class Overlay:
    def __init__(self, root):
        self.root = root
        self.state = DEFAULT_STATE
        self.mtime = 0.0
        self.drag = None
        self.bg_count = 0
        self.task_dirs = []

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", KEY)
        root.configure(bg=KEY)

        cfg = load_config()
        self.bg_enabled = cfg.get("background_tasks", True)
        self.bg_window = cfg.get("background_window_seconds", BG_WINDOW)
        self.ignore_before = cfg.get("ignore_tasks_before", 0)
        x = cfg.get("x")
        y = cfg.get("y")
        if x is None or y is None:
            x = root.winfo_screenwidth() - W - 24
            y = 120
        root.geometry("%dx%d+%d+%d" % (W, H, int(x), int(y)))

        self.canvas = tk.Canvas(root, width=W, height=H, bg=KEY, highlightthickness=0)
        self.canvas.pack()
        self.round_rect(2, 2, W - 2, H - 2, 14, fill=BODY, outline=EDGE)

        self.rings = {}
        self.circles = {}
        for name, cy in zip(ORDER, LAMP_Y):
            self.rings[name] = self.canvas.create_oval(
                LAMP_X - LAMP_R - 2, cy - LAMP_R - 2,
                LAMP_X + LAMP_R + 2, cy + LAMP_R + 2,
                fill="", outline=BODY, width=2,
            )
            self.circles[name] = self.canvas.create_oval(
                LAMP_X - LAMP_R, cy - LAMP_R,
                LAMP_X + LAMP_R, cy + LAMP_R,
                fill=LAMPS[name]["off"], outline="",
            )

        self.menu = tk.Menu(root, tearoff=0)  # rebuilt on each right-click

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_menu)

        threading.Thread(target=self.scan_loop, daemon=True).start()
        self.tick()

    def round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    # -- window interaction ------------------------------------------------
    def on_press(self, ev):
        self.drag = (ev.x_root - self.root.winfo_x(), ev.y_root - self.root.winfo_y())

    def on_drag(self, ev):
        if self.drag:
            self.root.geometry("+%d+%d" % (ev.x_root - self.drag[0], ev.y_root - self.drag[1]))

    def on_release(self, _ev):
        self.drag = None
        save_config(x=self.root.winfo_x(), y=self.root.winfo_y())

    def on_menu(self, ev):
        self.menu.delete(0, "end")
        self.menu.add_command(label="Claude: %s" % self.state, state="disabled")
        self.menu.add_command(label="Background tasks: %d" % self.bg_count, state="disabled")
        self.menu.add_separator()
        self.menu.add_command(
            label="%s Background tasks turn it yellow" % ("[x]" if self.bg_enabled else "[  ]"),
            command=self.toggle_background,
        )
        if self.bg_count:
            self.menu.add_command(
                label="Ignore these %d as stuck" % self.bg_count, command=self.ignore_current
            )
        self.menu.add_separator()
        self.menu.add_command(label="Reset position", command=self.reset_position)
        self.menu.add_command(label="Quit overlay", command=self.root.destroy)
        try:
            self.menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            self.menu.grab_release()

    def toggle_background(self):
        self.bg_enabled = not self.bg_enabled
        if not self.bg_enabled:
            self.bg_count = 0
        save_config(background_tasks=self.bg_enabled)

    def ignore_current(self):
        """Treat every task output file that exists right now as dead."""
        self.ignore_before = time.time()
        self.bg_count = 0
        save_config(ignore_tasks_before=self.ignore_before)

    def reset_position(self):
        self.root.geometry("+%d+%d" % (self.root.winfo_screenwidth() - W - 24, 120))
        save_config(x=self.root.winfo_x(), y=self.root.winfo_y())

    # -- state -------------------------------------------------------------
    def read_state(self):
        try:
            mtime = os.path.getmtime(STATE_FILE)
        except OSError:
            return
        if mtime == self.mtime:
            return
        self.mtime = mtime
        try:
            with open(STATE_FILE, encoding="utf-8", errors="replace") as fh:
                word = fh.read().strip().lower()
        except OSError:
            return
        if word in STATES:
            self.state = word

    def discover_task_dirs(self):
        """Find every <project>/<session>/tasks directory under the temp root.

        Most session directories never hold one -- of 1371 here, 87 did -- and
        the failed stats dominate the walk, so this runs rarely and the hot
        scan reuses the result.
        """
        found = []
        try:
            projects = list(os.scandir(TASKS_ROOT))
        except OSError:
            return found
        for project in projects:
            if not project.is_dir():
                continue
            try:
                sessions = list(os.scandir(project.path))
            except OSError:
                continue
            for session in sessions:
                if not session.is_dir():
                    continue
                tasks = os.path.join(session.path, "tasks")
                if os.path.isdir(tasks):
                    found.append(tasks)
        return found

    def count_background(self):
        """Count background tasks that still look alive.

        A task counts as alive when its output file carries no exit marker and
        has been touched recently. Claude Code fires no hook when a background
        task finishes, so the files are all we have; the mtime window stops
        output left behind by a killed session from pinning the light yellow.
        """
        now = time.time()
        count = 0
        for tasks in self.task_dirs:
            try:
                # the directory's own mtime moves when a task file is added,
                # so an old one cannot hold a task we care about
                if now - os.stat(tasks).st_mtime > self.bg_window:
                    continue
                entries = list(os.scandir(tasks))
            except OSError:
                continue
            for entry in entries:
                if not entry.name.endswith(".output"):
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                if now - st.st_mtime > self.bg_window:
                    continue
                if st.st_mtime <= self.ignore_before:
                    continue
                try:
                    with open(entry.path, "rb") as fh:
                        fh.seek(max(0, st.st_size - 512))
                        tail = fh.read()
                except OSError:
                    continue
                if not DONE_RE.search(tail):
                    count += 1
        return count

    def scan_loop(self):
        """Rescan off the UI thread; tick() only ever reads the cached count."""
        next_discover = 0.0
        while True:
            try:
                if time.time() >= next_discover:
                    self.task_dirs = self.discover_task_dirs()
                    next_discover = time.time() + BG_DISCOVER_EVERY
                self.bg_count = self.count_background() if self.bg_enabled else 0
            except Exception:
                self.bg_count = 0
            time.sleep(BG_SCAN_EVERY)

    def tick(self):
        self.read_state()

        state = self.state
        if self.bg_count and state in IDLE_STATES:
            state = "working"  # Claude is idle but something is still running
        lamp, anim = STATES.get(state, STATES[DEFAULT_STATE])
        spec = LAMPS[lamp]

        now = time.time()
        if anim == "pulse":
            level = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(now * 3.6))
        elif anim == "blink":
            level = 1.0 if (now % 1.1) < 0.65 else 0.12
        else:
            level = 1.0

        for name in ORDER:
            if name == lamp:
                self.canvas.itemconfig(self.circles[name], fill=blend(spec["off"], spec["on"], level))
                self.canvas.itemconfig(self.rings[name], outline=blend(BODY, spec["ring"], level * 0.5))
            else:
                self.canvas.itemconfig(self.circles[name], fill=LAMPS[name]["off"])
                self.canvas.itemconfig(self.rings[name], outline=BODY)

        # Re-assert topmost occasionally so newly-opened windows don't cover us.
        if int(now) % 3 == 0:
            self.root.attributes("-topmost", True)

        self.root.after(70, self.tick)


def main():
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
        lock.listen(1)
    except OSError:
        return  # another overlay already owns the port

    os.makedirs(BASE, exist_ok=True)
    root = tk.Tk()
    Overlay(root)
    root.mainloop()


if __name__ == "__main__":
    main()
