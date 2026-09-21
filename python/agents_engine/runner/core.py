"""The loop: one target, one pass through its queue.

Everything an agent does not own happens here. The agent's hooks are asked four
things along the way (is this item eligible, in what order, what is Claude
asked, and where does the answer go) and nothing else about the queue is theirs
to decide.
"""

import datetime as dt
import json
import os
import subprocess

from . import claude, daylog, settings, stream

MAX_FAILS = daylog.MAX_FAILS


class Agent(object):
    """The hooks module plus where it lives. Every default a hook may leave out is here."""

    def __init__(self, hooks, root, script=None):
        self.hooks = hooks
        self.root = os.path.abspath(root)
        self.id = hooks.ID
        self.name = getattr(hooks, "NAME", hooks.ID)
        self.blurb = getattr(hooks, "BLURB", "")
        self.state_dir = os.path.join(self.root, getattr(hooks, "STATE", "state"))
        self.script = script or os.path.join(self.root, "run.py")

    def targets(self):
        return list(self.hooks.targets())

    def target(self, target_id):
        for t in self.targets():
            if t["id"] == target_id:
                return t
        return None

    def manifest(self, target):
        return stream.load_manifest(os.path.join(self.root, self.hooks.stream(target)))

    def title(self, target):
        return "%s · %s" % (self.name, target.get("name") or target["id"])

    def log(self, line, now=None):
        os.makedirs(self.state_dir, exist_ok=True)
        stamp = (now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(self.state_dir, "runner.log"), "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (stamp, line))

    def lock_path(self, target_id):
        return os.path.join(self.state_dir, target_id, ".lock")

    def ledger_path(self, target_id):
        return os.path.join(self.state_dir, target_id, "ledger.json")

    def load_ledger(self, target_id):
        try:
            with open(self.ledger_path(target_id), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_ledger(self, target_id, ledger):
        path = self.ledger_path(target_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)

    def call(self, name, *args, default=None):
        fn = getattr(self.hooks, name, None)
        return fn(*args) if fn else default


def _now():
    return dt.datetime.now().astimezone()


def select(agent, target, m, only=None, use_ledger=True):
    """(to_run, left): the items this pass would work, and the ones it passes over with why."""
    where = stream.folder(m, agent.root, target["id"])
    ledger = agent.load_ledger(target["id"]) if use_ledger else {}
    todo, left = [], []
    for item in stream.items(where, m):
        f = item["fields"]
        if only and only not in (item["id"], item["title"], item["name"]):
            continue
        if f.get("state", "ready") != "ready":
            continue
        if f.get("owner") not in (None, "", agent.id):
            continue
        entry = {"id": item["id"], "title": item["title"]}
        if stream.truthy(f.get("needs_you")):
            left.append(dict(entry, kind="waiting", why="waiting on you (marked needs_you)"))
            continue
        why = agent.call("eligible", item, target)
        if why:
            left.append(dict(entry, kind="refused", why=why))
            continue
        row = ledger.get(item["id"]) or {}
        if use_ledger and not only and row.get("last") == "ran" and row.get("fingerprint") == stream.fingerprint(item):
            left.append(dict(entry, kind="unchanged", why="unchanged since %s" % row.get("when", "")[:10]))
            continue
        todo.append(item)
    ordered = agent.call("order", todo, target)
    return (ordered if ordered is not None else todo), left


def options(agent, item, target, conf):
    opts = dict(claude.DEFAULTS, cwd=agent.root)
    opts.update(agent.call("options", item, target, default={}) or {})
    if conf.get("item_budget"):
        opts["budget"] = float(conf["item_budget"])
    return opts


def notify(agent, target, ran, failed):
    if os.environ.get("AGENTS_RUNNER_QUIET") or not (ran or failed):
        return
    text = "%d ran, %d failed. The day's log is in %s." % (ran, failed, agent.name)
    script = 'display notification %s with title %s' % (json.dumps(text), json.dumps(agent.title(target)))
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_target(agent, target, trigger="schedule", only=None, dry=False, now=None):
    """One pass. Returns the run record written to the day's log (or the plan, when dry)."""
    now = now or _now()
    tid = target["id"]
    conf = settings.load(agent.state_dir, agent.hooks, tid)
    m = agent.manifest(target)
    lock = stream.lock_path(m, agent.root)
    todo, left = select(agent, target, m, only=only)

    if dry:
        agent.log("dry run for %s: %d would run, %d not run" % (tid, len(todo), len(left)))
        for item in todo:
            agent.log("  would run  %s" % item["title"])
        for l in left:
            agent.log("  not run    %s · %s" % (l["title"], l["why"]))
        return {"dry": True, "would_run": [i["title"] for i in todo], "left": left}

    ledger = agent.load_ledger(tid)
    run = {"started": now.isoformat(timespec="seconds"), "trigger": trigger, "budget": conf["budget"],
           "cost": 0.0, "stopped": None, "did": [], "left": list(left)}
    agent.log("start %s: %d to run, %d not run" % (tid, len(todo), len(left)))
    attempts = []

    for n, item in enumerate(todo):
        at = _now()
        stop = None
        if run["cost"] >= float(conf["budget"]):
            stop = "the night's budget of $%.2f was reached" % float(conf["budget"])
        elif conf.get("max_items") and len(run["did"]) >= int(conf["max_items"]):
            stop = "the cap of %d items a night was reached" % int(conf["max_items"])
        elif trigger == "schedule" and at.hour not in conf["hours"]:
            stop = "the scheduled hours ended"
        if stop:
            run["stopped"] = stop
            for rest in todo[n:]:
                run["left"].append({"id": rest["id"], "title": rest["title"], "kind": "stopped",
                                    "why": "not reached: %s" % stop})
            agent.log("stopped %s: %s" % (tid, stop))
            break

        try:
            stream.write(item, {"state": "doing", "owner": agent.id}, lock, agent.name)
        except stream.QueueError as exc:
            run["left"].append({"id": item["id"], "title": item["title"], "kind": "busy",
                                "why": "the queue was being written by something else (%s)" % exc})
            continue

        opts = options(agent, item, target, conf)
        agent.log("  > %s" % item["title"])
        began = _now()
        res = claude.run(agent.hooks.prompt(item, target), opts)
        run["cost"] += res.cost

        landed = None
        if not res.error:
            try:
                landed = agent.hooks.land(item, res.as_dict(), target) or {}
            except Exception as exc:  # noqa: BLE001 - a hook's bug is one failed item, not a dead run
                res.error, res.kind = "%s: %s" % (type(exc).__name__, exc), "land"

        row = ledger.get(item["id"]) or {}
        entry = {"id": item["id"], "title": item["title"], "when": began.isoformat(timespec="seconds"),
                 "cost": round(res.cost, 4), "session": res.session}

        if res.error and res.kind == "limit":
            stream.write(item, {"state": "ready", "owner": agent.id}, lock, agent.name)
            why, _ = claude.explain(res, opts)
            run["stopped"] = why
            run["left"].append(dict(entry, kind="stopped", why="not reached: %s" % why))
            for rest in todo[n + 1:]:
                run["left"].append({"id": rest["id"], "title": rest["title"], "kind": "stopped",
                                    "why": "not reached: %s" % why})
            agent.log("stopped %s: %s" % (tid, why))
            break

        if res.error:
            why, fix = claude.explain(res, opts)
            hook_says = agent.call("explain", res.error, res.kind)
            if hook_says:
                why, fix = hook_says
            fails = int(row.get("fails") or 0) + 1
            set_aside = fails >= MAX_FAILS
            if set_aside:
                stream.write(item, {"state": "blocked", "owner": "me", "needs_you": True,
                                    "feedback": "Failed %d times. Last: %s" % (fails, why)}, lock, agent.name)
            else:
                stream.write(item, {"state": "ready", "owner": agent.id}, lock, agent.name)
            ledger[item["id"]] = dict(row, title=item["title"], fails=fails, last="failed",
                                      when=entry["when"], error=res.error[:300])
            agent.save_ledger(tid, ledger)
            run["did"].append(dict(entry, outcome="failed", tone="bad", label="failed", why=why, fix=fix,
                                   fails=fails, set_aside=set_aside, kind=res.kind))
            agent.log("  failed %s · %s" % (item["title"], why))
            attempts.append((False, res.kind if res.kind != "other" else why))
            if len(attempts) == 2 and not attempts[0][0] and not attempts[1][0] and attempts[0][1] == attempts[1][1]:
                run["stopped"] = "the first two items failed the same way (%s)" % why
                for rest in todo[n + 1:]:
                    run["left"].append({"id": rest["id"], "title": rest["title"], "kind": "stopped",
                                        "why": "not reached: the first two failed the same way"})
                agent.log("stopped %s: %s" % (tid, run["stopped"]))
                break
            continue

        changes = {"state": "review", "owner": "me", "seen": False}
        changes.update(landed.get("fields") or {})
        if landed.get("needs_you"):
            changes["needs_you"] = True
        if landed.get("feedback"):
            changes["feedback"] = landed["feedback"]
        stream.write(item, changes, lock, agent.name)
        ledger[item["id"]] = {"title": item["title"], "fingerprint": stream.fingerprint(item), "fails": 0,
                              "last": "ran", "when": entry["when"], "ref": landed.get("ref")}
        agent.save_ledger(tid, ledger)
        run["did"].append(dict(entry, outcome="ran", tone="good", label=landed.get("label") or "done",
                               summary=landed.get("summary") or "done", ref=landed.get("ref"),
                               detail=landed.get("detail")))
        agent.log("  ran %s · $%.2f" % (item["title"], res.cost))
        attempts.append((True, None))

    run["finished"] = _now().isoformat(timespec="seconds")
    run["cost"] = round(run["cost"], 4)
    daylog.add_run(agent.state_dir, tid, run, agent.title(target))
    daylog.prune(agent.state_dir, tid, now.date())
    ran = len([d for d in run["did"] if d["outcome"] == "ran"])
    failed = len(run["did"]) - ran
    agent.log("done %s: %d ran, %d failed, %d not run, $%.2f%s" % (
        tid, ran, failed, len(run["left"]), run["cost"], " (stopped early)" if run["stopped"] else ""))
    if trigger == "schedule":
        notify(agent, target, ran, failed)
    return run
