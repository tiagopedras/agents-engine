"""The single hourly wake for every agent on this machine.

    python3 -m agents_engine.wake            wake every agent that has a `wake` command
    python3 -m agents_engine.wake --list     say which ones it would wake, and wake nothing

launchd runs this once an hour (`launchd/com.tiagopedras.agents-wake.plist`). It
holds no policy: it finds every agent the way the dashboard does and starts each
one's `wake` command in its own process, without waiting. Whether this hour is
one of an agent's own is the agent's question, answered from its own schedule.

An agent with no `wake` command is not woken here, which is how an agent still
on its own plist keeps working until it moves over.
"""

import datetime as dt
import os
import subprocess
import sys

from . import discover

LOG = os.path.expanduser("~/Library/Logs/agents-wake.log")


def _log(line):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("%s  %s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), line))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    agents = [a for a in discover.find() if a.get("wake")]
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
