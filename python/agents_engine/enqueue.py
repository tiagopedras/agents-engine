"""Put a request on any agent's queue, and optionally run it now.

    python3 -m agents_engine.enqueue
        list the agents that take requests
    python3 -m agents_engine.enqueue <agent> --title "..." [--target T] [--field k=v ...] [--body "..."]
        a new item, for an agent that owns its queue (the UX agent)
    python3 -m agents_engine.enqueue <agent> --item "<entry>" [--target T]
        an existing entry, for an agent that reads someone else's list (improve-agent)
    add --now to start that one item straight away, whatever the hours

Queuing is the only way work reaches an agent. A scheduled run works what is
queued, inside its own hours and the machine's fences (runner/fences.py); --now
is the on-demand path and goes through the same runner, lock and log.
"""

import argparse
import json
import subprocess
import sys

from . import discover


def _agent(key):
    for a in discover.find():
        if key in (a["id"], a.get("key"), a["name"]):
            return a
    return None


def _ask(agent, verb, req):
    """The agent's JSON answer, whether or not it exited 0: a refusal is still an answer."""
    cmd = agent.get(verb)
    if not cmd:
        return {"ok": False, "error": "%s has no %r command" % (agent["name"], verb)}
    try:
        proc = subprocess.run(cmd, cwd=agent["cwd"], input=json.dumps(req), capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "no answer").strip()[-300:]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agents_engine.enqueue")
    ap.add_argument("agent", nargs="?")
    ap.add_argument("--target")
    ap.add_argument("--title")
    ap.add_argument("--item")
    ap.add_argument("--body", default="")
    ap.add_argument("--field", action="append", default=[], help="key=value, repeatable")
    ap.add_argument("--now", action="store_true")
    args = ap.parse_args(argv)

    if not args.agent:
        for a in discover.find():
            print("%-16s %s" % (a["id"], "takes requests" if a.get("enqueue") else "no enqueue command"))
        return 0
    agent = _agent(args.agent)
    if not agent:
        print("no agent called %r" % args.agent, file=sys.stderr)
        return 2
    fields = {}
    for kv in args.field:
        if "=" not in kv:
            print("--field wants key=value, not %r" % kv, file=sys.stderr)
            return 2
        k, v = kv.split("=", 1)
        fields[k.strip()] = v.strip()
    req = {"target": args.target, "title": args.title, "item": args.item, "fields": fields, "body": args.body}
    out = _ask(agent, "enqueue", req)
    if out.get("ok") and args.now:
        ref = out.get("id") or args.item or args.title
        started = _ask(agent, "run", {"action": "run", "target": out.get("target"), "item": ref})
        out["started"] = bool(started.get("ok"))
        if not started.get("ok"):
            out["error"] = started.get("error")
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
