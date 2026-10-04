"""Install (or remove) the Claude Code hooks that drive the traffic signal.

    python install.py              add the hooks to ~/.claude/settings.json
    python install.py --uninstall  remove them again

The file is backed up before every change and every other setting and hook in it
is left alone. Running the installer twice is harmless: it replaces its own hooks
rather than adding duplicates.
"""

import argparse
import json
import os
import shutil
import sys
import time

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
SIGNAL_DIR = os.path.join(CLAUDE_DIR, "signal")
STATE_REL = ".claude/signal/state.txt"  # also how our own hooks are recognised

# hook event -> state word written to state.txt
EVENTS = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "PermissionRequest": "attention",
    "Elicitation": "attention",
    "Notification": "attention",
    "Stop": "done",
    "SessionEnd": "done",
}


def signal_hook(word):
    # Shell form on purpose: the exec form ("command" + "args") failed on Windows
    # with "The filename, directory name, or volume label syntax is incorrect".
    return {
        "type": "command",
        "shell": "bash",
        "command": "printf '%s' > \"$HOME/%s\"" % (word, STATE_REL),
        "timeout": 5,
    }


def is_ours(hook):
    blob = str(hook.get("command", "")) + "".join(map(str, hook.get("args", []) or []))
    return STATE_REL in blob.replace("\\", "/")


def strip_ours(hooks):
    removed = 0
    for event in list(hooks):
        entries = hooks[event]
        for entry in entries:
            before = len(entry.get("hooks", []))
            entry["hooks"] = [h for h in entry.get("hooks", []) if not is_ours(h)]
            removed += before - len(entry["hooks"])
        entries[:] = [e for e in entries if e.get("hooks")]
        if not entries:
            del hooks[event]
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--uninstall", action="store_true", help="remove the hooks")
    parser.add_argument(
        "--settings",
        default=os.path.join(CLAUDE_DIR, "settings.json"),
        help="settings file to edit (default: ~/.claude/settings.json)",
    )
    args = parser.parse_args()

    cfg = {}
    if os.path.exists(args.settings):
        with open(args.settings, encoding="utf-8") as fh:
            try:
                cfg = json.load(fh)
            except json.JSONDecodeError as exc:
                sys.exit("%s is not valid JSON (%s); fix it first." % (args.settings, exc))
        backup = "%s.bak-%s" % (args.settings, time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(args.settings, backup)
        print("backed up  ", backup)

    hooks = cfg.setdefault("hooks", {})
    removed = strip_ours(hooks)

    if args.uninstall:
        if not hooks:
            del cfg["hooks"]
        print("removed    ", removed, "hooks")
    else:
        for event, word in EVENTS.items():
            hooks.setdefault(event, []).append({"hooks": [signal_hook(word)]})
        os.makedirs(SIGNAL_DIR, exist_ok=True)
        state = os.path.join(SIGNAL_DIR, "state.txt")
        if not os.path.exists(state):
            with open(state, "w", encoding="utf-8") as fh:
                fh.write("idle")
        print("installed  ", len(EVENTS), "hooks", "(replaced %d old)" % removed if removed else "")

    os.makedirs(os.path.dirname(os.path.abspath(args.settings)), exist_ok=True)
    with open(args.settings, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print("wrote      ", args.settings)
    if not args.uninstall:
        print("\nHooks load when a session starts: open a new Claude Code session, then")
        print("run start-signal.bat (or: pythonw overlay.pyw).")


if __name__ == "__main__":
    main()
