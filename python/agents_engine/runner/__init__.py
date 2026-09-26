"""The runner: works through an agent's queue unattended. See RUNNER.md.

An agent built on it keeps a `run.py` of a few lines that puts this package on
the path and calls `main(hooks, root)`, and an `agent.json` whose commands all
point at that file:

    python3 run.py --wake            what the single hourly wake calls
    python3 run.py --state           the dashboard's card
    python3 run.py --apply           one settings change on stdin
    python3 run.py --run             one action on stdin, started detached
    python3 run.py --activity        what happened since an instant on stdin
    python3 run.py --stream-apply    the queue's writer, one transition on stdin
    python3 run.py --enqueue         one request on stdin: {target, title, fields, body} or {target, item}
    python3 run.py --now [--target T] [--item X] [--dry-run]
                                     a pass by hand, in the foreground
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

from . import core, daylog, fences, lock, settings, stream
from .core import Agent

WAKE_LABEL = "com.tiagopedras.agents-wake"


def _stdin():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return None


def _out(obj):
    print(json.dumps(obj, indent=None))
    return 0 if obj.get("ok", True) else 1


def wake(agent, now=None):
    """Asked every hour. Each target that names this hour and is on gets one pass.

    Targets run one after another, so an agent-wide ceiling (`agent_budget()` in
    the hooks, when there is one) is shared across them in the order they come.
    """
    now = now or dt.datetime.now().astimezone()
    left = agent.call("agent_budget")
    fences.prune(now.date())
    for target in agent.targets():
        tid = target["id"]
        conf = settings.load(agent.state_dir, agent.hooks, tid)
        if not conf["on"] or now.hour not in conf["hours"]:
            daylog.add_wake(agent.state_dir, tid, now, "off" if not conf["on"] else "idle", agent.title(target))
            continue
        taken, note = lock.acquire(agent.lock_path(tid))
        if note:
            agent.log("%s: %s" % (tid, note))
        if not taken:
            daylog.add_wake(agent.state_dir, tid, now, "busy", agent.title(target))
            continue
        try:
            daylog.add_wake(agent.state_dir, tid, now, "ran", agent.title(target))
            # Once per scheduled pass, whether or not anything is due: work the
            # agent does on its own clock, such as the planning agent's briefings.
            agent.call("on_wake", target)
            run = core.run_target(agent, target, trigger="schedule", now=now, budget_left=left)
            if left is not None:
                left = max(0.0, left - run["cost"])
        except Exception as exc:  # noqa: BLE001 - logged so a broken target never silences the others
            agent.log("%s: the run crashed: %s: %s" % (tid, type(exc).__name__, exc))
        finally:
            lock.release(agent.lock_path(tid))
    return 0


def by_hand(agent, target_id=None, item=None, dry=False):
    targets = [agent.target(target_id)] if target_id else agent.targets()
    if target_id and not targets[0]:
        print("no target called %r" % target_id, file=sys.stderr)
        return 2
    for target in targets:
        if dry:
            plan = core.run_target(agent, target, only=item, dry=True)
            print("%s: %d would run%s" % (target["id"], len(plan["would_run"]),
                                          (" (%s)" % plan["note"]) if plan.get("note") else ""))
            for t in plan["would_run"]:
                print("  run   %s" % t)
            for l in plan["left"]:
                print("  skip  %s · %s" % (l["title"], l["why"]))
            continue
        taken, note = lock.acquire(agent.lock_path(target["id"]))
        if not taken:
            print("%s: %s" % (target["id"], note))
            continue
        try:
            run = core.run_target(agent, target, trigger="manual", only=item)
            print("%s: %d done, %d not run, $%.2f%s" % (
                target["id"], len(run["did"]), len(run["left"]), run["cost"],
                (", stopped: %s" % run["stopped"]) if run["stopped"] else ""))
        finally:
            lock.release(agent.lock_path(target["id"]))
    return 0


def _job():
    plist = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % WAKE_LABEL)
    try:
        loaded = subprocess.run(["launchctl", "list", WAKE_LABEL], capture_output=True,
                                timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        loaded = False
    return {"label": WAKE_LABEL, "installed": os.path.exists(plist), "loaded": loaded}


def _tail(agent, n=12):
    try:
        with open(os.path.join(agent.state_dir, "runner.log"), encoding="utf-8") as fh:
            return [l.rstrip("\n") for l in fh.readlines()[-n:]]
    except OSError:
        return []


def target_card(agent, target):
    tid = target["id"]
    conf = settings.load(agent.state_dir, agent.hooks, tid)
    problems = list(agent.call("problems", target, default=[]) or [])
    groups, counts = {}, {"ready": 0, "review": 0, "blocked": 0}
    labels = {}
    try:
        todo, left, m = core.select(agent, target)
        labels = (m or {}).get("states") or {"ready": "ready", "blocked": "set aside"}
        if m is not None:
            where = stream.folder(m, agent.root, tid)
            if not os.path.isdir(where):
                problems.append("The queue folder %s does not exist yet." % os.path.relpath(where, agent.root))
        held = {l["id"] or l["title"]: l for l in left}
        items, _ = agent.items(target)
        for item in items:
            st = (item.get("fields") or {}).get("state", "ready")
            note = held.get(item.get("id") or item["title"])
            if m is None and note and note["kind"] == "blocked":
                st = "blocked"
            if st == "done":
                continue
            if st in counts:
                counts[st] += 1
            why = (note["why"] if note and note["kind"] in ("refused", "waiting", "blocked") else "") \
                or (item.get("fields") or {}).get("feedback") or ""
            tone = "warn" if st in ("review", "blocked") or why else ("good" if st == "ready" else None)
            groups.setdefault(st, []).append({"text": item["title"], "state": labels.get(st, st),
                                              "status": st, "tone": tone, "why": why})
    except stream.QueueError as exc:
        problems.append(str(exc))

    last = daylog.latest(agent.state_dir, tid)
    last_run = None
    tone = None
    if last:
        ran, left, failed, stopped, cost = daylog.merged(last)
        final = last["runs"][-1]
        last_run = {"when": final["started"][:16].replace("T", " "),
                    "meta": "$%.2f · %d ran · %d failed · %d not run" % (cost, len(ran), len(failed), len(left)),
                    "skipped": final.get("stopped"),
                    "rows": [{"tone": d["tone"], "label": d["label"], "text": d["title"],
                              "tag": d.get("ref") or ""} for d in ran + failed]}
        if any(d["outcome"] == "failed" for d in final.get("did") or []):
            tone = "bad"

    order = ["ready", "doing", "review", "blocked", "backlog"]
    card = {
        "id": tid, "name": target.get("name") or tid, "subtitle": target.get("subtitle", ""),
        "note": target.get("note", ""),
        "on": conf["on"], "switchable": True, "hours": conf["hours"],
        "hours_label": "Hours it may start work", "hours_editable": True,
        "problems": problems,
        "actions": [{"id": "dry", "label": "Dry run"}, {"id": "run", "label": "Run now"}],
        "last_run": last_run,
        "counts": [
            {"n": counts["ready"], "l": labels.get("ready", "ready").lower(), "kind": "good", "status": "ready",
             "opens": "detail"},
            {"n": counts["review"], "l": labels.get("review", "review").lower(), "kind": "warn",
             "status": "review", "opens": "detail"},
            {"n": counts["blocked"], "l": labels.get("blocked", "blocked").lower(), "kind": "warn",
             "status": "blocked", "opens": "detail"},
        ],
        "detail": {"groups": [{"name": labels.get(s, s), "cards": groups[s]} for s in order if s in groups]},
        "fields": [dict({k: v for k, v in f.items() if k != "default"}, value=conf.get(f["key"]))
                   for f in settings.fields(agent.hooks)],
        "_tone": tone,
    }
    # The agent may add to the card or replace parts of it: its own counts,
    # branches, stats. Whatever it returns is the card.
    return agent.call("card", target, card, default=card) or card


def state(agent):
    targets = [target_card(agent, t) for t in agent.targets()]
    on = [t for t in targets if t["on"]]
    tones = [t.pop("_tone", None) for t in targets]
    tone = "bad" if "bad" in tones else ("ok" if on else "warn")
    running = any(lock.holder(agent.lock_path(t["id"])) for t in targets)
    return {
        "id": agent.id, "name": agent.name, "blurb": agent.blurb,
        "summary": "On for %d of %d · %s" % (len(on), len(targets), "running now" if running else
                                              ("%d hours set" % sum(len(t["hours"]) for t in on) if on else "off")),
        "tone": tone, "job": _job(), "running": running, "log": _tail(agent),
        "hours_preferred": getattr(agent.hooks, "HOURS_PREFERRED", None),
        "actions": list(agent.call("actions", default=[]) or []) + [
            {"id": "dry", "label": "Dry run"}, {"id": "run", "label": "Run now", "primary": True}],
        "stats": agent.call("stats", targets, default=None) or [],
        "targets": targets,
    }


def apply(agent, req):
    tid = (req or {}).get("target")
    if not agent.target(tid or ""):
        return {"ok": False, "error": "no target called %r" % tid}
    err = settings.save(agent.state_dir, agent.hooks, tid, (req or {}).get("changes") or {})
    return {"ok": False, "error": err} if err else {"ok": True}


def start(agent, req):
    action = (req or {}).get("action")
    tid = (req or {}).get("target")
    if action not in ("run", "dry"):
        # An agent's own action, such as looking for new repos. Answered in the
        # foreground, since the answer is the point.
        answer = agent.call("action", action, tid)
        return answer if answer is not None else {"ok": False, "error": "unknown action %r" % action}
    if tid and not agent.target(tid):
        return {"ok": False, "error": "no target called %r" % tid}
    item = (req or {}).get("item")
    cmd = [sys.executable, agent.script, "--now"] + (["--target", tid] if tid else []) + (
        ["--item", item] if item else []) + (["--dry-run"] if action == "dry" else [])
    os.makedirs(agent.state_dir, exist_ok=True)
    log = open(os.path.join(agent.state_dir, "runner.log"), "a", encoding="utf-8")
    subprocess.Popen(cmd, cwd=agent.root, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    return {"ok": True}


def activity(agent, req):
    now = dt.datetime.now().astimezone()
    since_raw = (req or {}).get("since")
    try:
        since = dt.datetime.fromisoformat(since_raw) if since_raw else now - dt.timedelta(hours=24)
    except ValueError:
        return {"ok": False, "error": "since is not an ISO 8601 instant"}
    if since.tzinfo is None:
        since = since.astimezone()
    runs, cost, wakes_total, wakes_worked = [], 0.0, 0, 0
    for target in agent.targets():
        for day in daylog.days(agent.state_dir, target["id"], since.date(), now.date()):
            for hour, what in (day.get("wakes") or {}).items():
                at = dt.datetime.fromisoformat("%sT%s:59:59" % (day["date"], hour)).astimezone()
                if at >= since:
                    wakes_total += 1
                    wakes_worked += 1 if what == "ran" else 0
            for r in day["runs"]:
                if dt.datetime.fromisoformat(r["started"]) < since:
                    continue
                cost += r.get("cost") or 0.0
                runs.append({
                    "target": target["id"], "started": r["started"], "finished": r.get("finished"),
                    "cost": r.get("cost") or 0.0, "stopped": r.get("stopped"),
                    "where": target.get("where") or os.path.relpath(
                        daylog.folder(agent.state_dir, target["id"]), agent.root),
                    "did": [{"outcome": d["outcome"], "tone": d["tone"], "label": d["label"], "title": d["title"],
                             "summary": d.get("summary") or d.get("why") or "", "ref": d.get("ref"),
                             "cost": d.get("cost"), "detail": d.get("detail") or d.get("fix") or "",
                             "when": d.get("when")} for d in r.get("did") or []],
                    "left": [{"title": l["title"], "why": l["why"]} for l in r.get("left") or []],
                })
    runs.sort(key=lambda r: r["started"])
    return {"id": agent.id, "name": agent.name, "since": since.isoformat(timespec="seconds"),
            "cost": round(cost, 4), "unit": "$", "wakes": {"total": wakes_total, "worked": wakes_worked},
            "runs": runs}


def stream_apply(agent, req):
    target = agent.target(((req or {}).get("item") or {}).get("group") or (req or {}).get("target") or "")
    if not target:
        return {"ok": False, "error": "name the target in item.group"}
    m = agent.manifest(target)
    return stream.apply(m, agent.root, dict(req, target=target["id"]), agent.name)


def enqueue(agent, req):
    """Put one request on an agent's queue. Nothing runs until the queue is worked.

    An agent that owns its queue gets a new item, `ready` and its own. An agent
    that only reads a queue something else writes answers through its own
    `enqueue(target, req)` hook, or says where requests for it go instead
    (`QUEUE_HINT`), such as the board for the planning agent.
    """
    if not agent.owns_queue and not hasattr(agent.hooks, "enqueue"):
        return {"ok": False, "error": getattr(agent.hooks, "QUEUE_HINT", None)
                or "%s takes no requests from here" % agent.name}
    targets = agent.targets()
    tid = req.get("target")
    if not tid and len(targets) == 1:
        tid = targets[0]["id"]
    target = agent.target(tid) if tid else None
    if not target:
        return {"ok": False, "error": "name a target: %s" % ", ".join(t["id"] for t in targets)}
    if not agent.owns_queue:
        return agent.hooks.enqueue(target, req)
    title = " ".join((req.get("title") or "").split())
    if not title:
        return {"ok": False, "error": "a request needs a title"}
    m = agent.manifest(target)
    try:
        path = stream.create(m, agent.root, target["id"], title, req.get("fields") or {}, req.get("body") or "",
                             agent.id, stream.lock_path(m, agent.root), "enqueue")
    except (stream.QueueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    item = stream.read(path)
    why = agent.call("eligible", item, target)
    return {"ok": True, "target": target["id"], "path": os.path.relpath(path, agent.root),
            "id": item["fields"].get("id"), "warning": why}


def main(hooks, root, argv=None):
    ap = argparse.ArgumentParser(prog="run.py")
    for flag in ("--wake", "--state", "--apply", "--run", "--activity", "--stream-apply", "--enqueue", "--now"):
        ap.add_argument(flag, action="store_true")
    ap.add_argument("--target")
    ap.add_argument("--item")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    agent = Agent(hooks, root)

    if args.wake:
        return wake(agent)
    if args.now or args.dry_run:
        return by_hand(agent, args.target, args.item, dry=args.dry_run)
    if args.state:
        return _out(state(agent))
    req = _stdin()
    if req is None:
        return _out({"ok": False, "error": "stdin was not JSON"})
    if args.apply:
        return _out(apply(agent, req))
    if args.run:
        return _out(start(agent, req))
    if args.activity:
        return _out(activity(agent, req))
    if args.stream_apply:
        return _out(stream_apply(agent, req))
    if args.enqueue:
        return _out(enqueue(agent, req))
    ap.print_help()
    return 2
