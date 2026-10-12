"""The single hourly wake for every agent on this machine.

    python3 -m agents_engine.wake            wake every agent that has a `wake` command
    python3 -m agents_engine.wake --list     say which ones it would wake, and wake nothing
    python3 -m agents_engine.wake --root DIR look for agents under DIR rather than ~/Code

    python3 -m agents_engine.wake install [--root DIR] [--dry-run]
    python3 -m agents_engine.wake uninstall
    python3 -m agents_engine.wake status

launchd runs this once an hour, from a job `install` writes for whoever runs it:
`~/Library/LaunchAgents/bench.agents-wake.plist`, pointing at this Python and
this copy of the package. It holds no policy: it finds every agent the way the
dashboard does and starts each one's `wake` command in its own process, without
waiting. Whether this hour is one of an agent's own is the agent's question,
answered from its own schedule.

`--root` is how a host keeps the wake to its own agents: the bench installer
passes its checkout, so only the agents inside it are found and woken. Given to
`install`, it is written into the job's arguments.

An agent with no `wake` command is not woken here, which is how an agent still
on its own plist keeps working until it moves over.
"""

import datetime as dt
import os
import plistlib
import shutil
import subprocess
import sys

from . import discover

LOG = os.path.expanduser("~/Library/Logs/agents-wake.log")

LABEL = "bench.agents-wake"
# Labels the job was written under before `install` existed. Still read, so a
# machine on a hand-linked plist shows as armed until it is swapped.
OLD_LABELS = ("com.tiagopedras.agents-wake",)

# The package's python/ folder, which the job runs from and puts on the path.
PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# launchd starts a job with a bare PATH, so the agents' own `python3` and
# `claude` have to be named. These follow the folders install finds them in.
BASE_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
             "~/.local/bin"]


def _log(line):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("%s  %s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), line))


def plist_path(label=LABEL):
    return os.path.expanduser("~/Library/LaunchAgents/%s.plist" % label)


def _search_path():
    found = [os.path.dirname(sys.executable)]
    claude = shutil.which("claude")
    if claude:
        found.append(os.path.dirname(claude))
    out = []
    for d in found + [os.path.expanduser(p) for p in BASE_PATH]:
        if d and d not in out:
            out.append(d)
    return ":".join(out)


def _root(path):
    return os.path.abspath(os.path.expanduser(path)) if path else None


def plist(root=None):
    """The job, as a dict for plistlib. Every hour at quarter past, and nothing else.

    The hours each agent runs at live in that agent's own settings, edited from
    the agents dashboard, so this wakes all of them and each one decides. With a
    `root`, the job looks for agents under that folder only.
    """
    args = [sys.executable, "-m", "agents_engine.wake"]
    if root:
        args += ["--root", _root(root)]
    return {
        "Label": LABEL,
        "ProgramArguments": args,
        "WorkingDirectory": PYTHON_DIR,
        "EnvironmentVariables": {"PATH": _search_path(), "PYTHONPATH": PYTHON_DIR},
        "StartCalendarInterval": {"Minute": 15},
        "StandardOutPath": LOG,
        "StandardErrorPath": LOG,
    }


def _domain():
    return "gui/%d" % os.getuid()


def _loaded(label):
    try:
        return subprocess.run(["launchctl", "list", label], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def job():
    """Whether the wake is written and loaded, under the current label or an old one.

    The first label that is loaded wins, then the first that is written, so a
    machine still on an old plist reads as armed rather than as missing.
    """
    seen = []
    for label in (LABEL,) + OLD_LABELS:
        seen.append({"label": label, "installed": os.path.exists(plist_path(label)),
                     "loaded": _loaded(label)})
    for want in ("loaded", "installed"):
        for j in seen:
            if j[want]:
                return j
    return seen[0]


def install(root=None, dry=False):
    if root and not os.path.isdir(_root(root)):
        print("%s is not a folder" % _root(root), file=sys.stderr)
        return 2
    body = plistlib.dumps(plist(root)).decode("utf-8")
    if dry:
        print(body, end="")
        return 0
    where = plist_path()
    os.makedirs(os.path.dirname(where), exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    # A job already loaded under this label keeps its old plist until it is
    # booted out, so a second install replaces it rather than failing.
    subprocess.run(["launchctl", "bootout", "%s/%s" % (_domain(), LABEL)], capture_output=True)
    with open(where, "w", encoding="utf-8") as fh:
        fh.write(body)
    proc = subprocess.run(["launchctl", "bootstrap", _domain(), where], capture_output=True, text=True)
    if proc.returncode != 0:
        print("wrote %s, but launchctl could not load it: %s"
              % (where, (proc.stderr or proc.stdout).strip()), file=sys.stderr)
        return 1
    print("installed and loaded %s" % where)
    for old in OLD_LABELS:
        if _loaded(old):
            print("%s is loaded as well, so every agent is woken twice an hour. Unload it with:\n"
                  "  launchctl bootout %s/%s" % (old, _domain(), old))
    return 0


def uninstall():
    where = plist_path()
    subprocess.run(["launchctl", "bootout", "%s/%s" % (_domain(), LABEL)], capture_output=True)
    if os.path.exists(where):
        os.remove(where)
        print("unloaded and removed %s" % where)
    else:
        print("%s was not installed" % where)
    return 0


def status():
    j = job()
    print("%s  %s  %s" % (j["label"], "installed" if j["installed"] else "not installed",
                          "loaded" if j["loaded"] else "not loaded"))
    print("plist  %s" % plist_path(j["label"]))
    print("log    %s" % LOG)
    print("root   %s" % (_installed_root(j["label"]) or discover.CODE))
    return 0 if j["loaded"] else 1


def _installed_root(label):
    try:
        with open(plist_path(label), "rb") as fh:
            args = plistlib.load(fh).get("ProgramArguments") or []
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return _flag(args, "--root")


def _flag(argv, name):
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) else None
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = _root(_flag(argv, "--root"))
    if argv and argv[0] == "install":
        return install(root, dry="--dry-run" in argv)
    if argv and argv[0] == "uninstall":
        return uninstall()
    if argv and argv[0] == "status":
        return status()
    agents = [a for a in discover.find(root) if a.get("wake")]
    if "--list" in argv:
        for a in agents:
            print("%s  %s" % (a["id"], a["cwd"]))
        return 0
    if not agents:
        _log("no agent has a wake command")
        return 0
    for a in agents:
        try:
            with open(LOG, "a", encoding="utf-8") as out:
                subprocess.Popen(a["wake"], cwd=a["cwd"], stdout=out, stderr=out,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
            _log("woke %s" % a["id"])
        except OSError as exc:
            _log("could not wake %s: %s" % (a["id"], exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
