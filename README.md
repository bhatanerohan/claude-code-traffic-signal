# Claude Code traffic signal

A tiny always-on-top traffic light for Windows that shows what Claude Code is
doing, so you can tell at a glance from another tab or window whether it's still
working, waiting on you, or done.

| Light              | Meaning                                                  |
|--------------------|----------------------------------------------------------|
| Yellow             | Claude is working, or a background task is still running |
| Red (blinking)     | Claude needs a permission or a decision from you         |
| Green              | Done / idle                                              |

Works with the Claude Code CLI and the Claude desktop app's Code tab — anything
that reads `~/.claude/settings.json`.

## Requirements

- Windows
- Python 3 with tkinter (the standard python.org installer includes it)
- Claude Code using Git Bash for hooks (the default on Windows when Git for
  Windows is installed)

No packages to install.

## Install

```bash
git clone https://github.com/bhatanerohan/claude-code-traffic-signal.git
cd claude-code-traffic-signal
python install.py
```

`install.py` adds nine hooks to `~/.claude/settings.json`. It backs the file up
first, leaves every other setting and hook alone, and is safe to run twice.

Hooks are read when a session starts, so **open a new Claude Code session**,
then start the light:

```bash
start-signal.bat
```

## Usage

- **Drag** with the left mouse button. The position is remembered.
- **Right-click** for the current state, the number of background tasks running,
  a toggle for background tracking, "Reset position", and "Quit overlay".
- **Stop** it with right-click → Quit overlay, or `stop-signal.bat`.
- Only one copy ever runs; starting it again is harmless.

To start it at login, put a shortcut to `start-signal.bat` in `shell:startup`.

## Uninstall

```bash
python install.py --uninstall
```

Then delete the folder and `~/.claude/signal/`.

## How it works

The hooks write one word into `~/.claude/signal/state.txt`; the overlay polls
that file and lights the matching lamp.

| Hook event                                         | State       |
|----------------------------------------------------|-------------|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`    | `working`   |
| `PermissionRequest`, `Elicitation`, `Notification` | `attention` |
| `Stop`, `SessionEnd`                               | `done`      |
| `SessionStart`                                     | `idle`      |

Each hook is a single `printf` into the file, so it adds almost nothing to a
tool call.

The hooks use the shell form (`"shell": "bash"`, `"command": "printf ..."`). The
exec form (`"command"` plus `"args"`) does not work on Windows in Claude Code
2.1.226: it fails with *"The filename, directory name, or volume label syntax is
incorrect."*

### Background tasks

A task started with `run_in_background` fires `PostToolUse` the instant it
launches and `Stop` when the turn ends, so hooks alone would turn the light green
while it was still running. No hook marks its completion — a hook trace shows
`TaskCreated`, `TaskCompleted`, `SubagentStart` and `SubagentStop` never fire for
one.

So the overlay also watches the filesystem. Claude Code writes each task's output
to `%TEMP%\claude\<project>\<session>\tasks\<id>.output` and appends a bracketed
line when it ends. A task counts as running when its file has none and was
touched within the last 10 minutes. If anything is running, green becomes yellow;
red always wins.

That closing line is not always an exit code. A killed task ends with `[killed]`,
and missing that once kept the light stuck on yellow. `DONE_RE` in `overlay.pyw`
matches the known endings:

    [exited with code N]   [killed]   [terminated ...]   [timed out ...]

It only matches at the very end of the file, so a command that prints one of
these mid-output doesn't count as finished. If Claude Code adds a new ending,
add it there.

The scan runs on a background thread. Task folders are re-discovered every 30s
and checked every 2s — roughly 1% of one CPU core.

## Limits

- **One light for every session.** All sessions write to the same `state.txt`,
  so the light shows the latest event from any of them. If one session finishes
  while another is still working, the light turns green. Background tasks are
  counted across all sessions, so those are covered.
- **A background task silent for more than 10 minutes** stops counting. Any
  output resets the timer, so this only affects tasks that print nothing.
- **A session killed mid-task** can leave a file with no closing line. It counts
  as running until the 10 minutes pass; right-click → "Ignore these N as stuck"
  clears it immediately.
- **A brand-new session's first background task** can take up to 30s to show.

## Settings

`~/.claude/signal/overlay-config.json` holds the light's position, plus:

| Key                         | Default | Meaning                                         |
|-----------------------------|---------|-------------------------------------------------|
| `background_tasks`          | `true`  | Let running background tasks turn the light yellow |
| `background_window_seconds` | `600`   | How long a silent task still counts as running  |
