"""The loop: one target, one pass through its queue.

Everything an agent does not own happens here. The agent's hooks are asked a
handful of things along the way (which items, is this one eligible, in what
order, what is Claude asked, where does the answer go) and nothing else about
the pass is theirs to decide.

Two kinds of queue. One the agent owns, a folder of documents named by
`stream(target)`, where the runner moves each item through its states on the
item itself. And one it only reads, named by `items(target)`, such as a repo's
IMPROVEMENTS.md or the to-do list, where something else is the only writer. For
that kind nothing is written back, and the runner's own ledger is the only
record of what was tried and how it went.
"""

import datetime as dt
import json
import os
import subprocess

from . import claude, daylog, fences, settings, stream

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
        self.owns_queue = not hasattr(hooks, "items")

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

    def target_dir(self, target_id):
        return os.path.join(self.state_dir, daylog.slug(target_id))

    def lock_path(self, target_id):
        """The agent may name its own, when something else already checks a lock by path."""
        if hasattr(self.hooks, "lock_path"):
            return self.hooks.lock_path(target_id)
        return os.path.join(self.target_dir(target_id), ".lock")

    def ledger_path(self, target_id):
        return os.path.join(self.target_dir(target_id), "ledger.json")

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

    def items(self, target):
        """(items, manifest or None). Items are dicts: id, title, fields, body, optional fingerprint."""
        if not self.owns_queue:
            return list(self.hooks.items(target)), None
        m = self.manifest(target)
        return stream.items(stream.folder(m, self.root, target["id"]), m), m

    def move(self, item, changes, m):
        """Write back onto an item, when the queue is the agent's own. Otherwise nothing."""
        if m is None:
            return item
        return stream.write(item, changes, stream.lock_path(m, self.root), self.name)


def _now():
    return dt.datetime.now().astimezone()


def fingerprint(item):
    return item.get("fingerprint") or stream.fingerprint(item)


def select(agent, target, only=None, use_ledger=True):
    """(to_run, left, manifest): what this pass would work, and what it passes over with why.

    `only` is also handed to an agent that supplies its own items, as
    target["only"], since a queue it does not own may need asking differently
    for one item by hand (the planning agent ignores its ledger for one).
    """
    items, m = agent.items(dict(target, only=only) if only else target)
    ledger = agent.load_ledger(target["id"]) if use_ledger else {}
    todo, left = [], []
    for item in items:
        f = item.get("fields") or {}
        if only and only not in (item.get("id"), item.get("title"), item.get("name")):
            continue
        if f.get("state", "ready") != "ready":
            continue
        if f.get("owner") not in (None, "", agent.id):
            continue
        entry = {"id": item.get("id") or "", "title": item["title"]}
        if stream.truthy(f.get("needs_you")):
            left.append(dict(entry, kind="waiting", why="waiting on you (marked needs_you)"))
            continue
        why = agent.call("eligible", item, target)
        if why:
            # A reason, or {"why": ..., "kind": "unchanged"} to have it folded
            # into the log's one line of unchanged items.
            if isinstance(why, dict):
                left.append(dict(entry, kind=why.get("kind") or "refused", why=why.get("why") or ""))
            else:
                left.append(dict(entry, kind="refused", why=why))
            continue
        row = ledger.get(item.get("id")) or {}
        same = row.get("fingerprint") == fingerprint(item)
        if use_ledger and not only and same and row.get("last") == "blocked":
            left.append(dict(entry, kind="blocked", why="set aside after failing: %s. Change it to try again"
                             % (row.get("why") or "see the log")))
            continue
        if use_ledger and not only and same and row.get("last") == "ran":
            left.append(dict(entry, kind="unchanged", why="unchanged since %s" % (row.get("when") or "")[:10]))
            continue
        todo.append(item)
    ordered = agent.call("order", todo, target)
    return (ordered if ordered is not None else todo), left, m


def options(agent, item, target, conf):
    opts = dict(claude.DEFAULTS, cwd=agent.root)
    opts.update(agent.call("options", item, target, default={}) or {})
    if conf.get("item_budget"):
        opts["budget"] = float(conf["item_budget"])
    return opts


def notify(agent, target, run):
    ran = len([d for d in run["did"] if d["outcome"] == "ran"])
    failed = len(run["did"]) - ran
    if os.environ.get("AGENTS_RUNNER_QUIET") or not (ran or failed):
        return
    text = "%d ran, %d failed. The day's log is in %s." % (ran, failed, agent.name)
    if hasattr(agent.hooks, "notify"):
        try:
            agent.hooks.notify(target, run, text)
        except Exception as exc:  # noqa: BLE001 - a notification never fails a run
            agent.log("notify failed: %s" % exc)
        return
    script = 'display notification %s with title %s' % (json.dumps(text), json.dumps(agent.title(target)))
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _left(rest, why):
    return [{"id": r.get("id") or "", "title": r["title"], "kind": "stopped", "why": "not reached: %s" % why}
            for r in rest]


def run_target(agent, target, trigger="schedule", only=None, dry=False, now=None, budget_left=None):
    """One pass. Returns the run record written to the day's log (or the plan, when dry)."""
    now = now or _now()
    tid = target["id"]
    conf = settings.load(agent.state_dir, agent.hooks, tid)
    todo, left, m = select(agent, target, only=only)
    if conf.get("max_items"):
        cap = int(conf["max_items"])
        left += _left(todo[cap:], "the cap of %d items a night" % cap)
        todo = todo[:cap]

    if dry:
        prep = agent.call("before", target, todo, True) if todo else None
        agent.log("dry run for %s: %d would run, %d not run" % (tid, len(todo), len(left)))
        for item in todo:
            agent.log("  would run  %s" % item["title"])
        for l in left:
            agent.log("  not run    %s · %s" % (l["title"], l["why"]))
        return {"dry": True, "would_run": [i["title"] for i in todo], "left": left,
                "note": (prep.get("note") if isinstance(prep, dict) else prep) or None}

    ledger = agent.load_ledger(tid)
    budget = float(conf["budget"])
    if budget_left is not None:
        budget = min(budget, budget_left)
    run = {"started": now.isoformat(timespec="seconds"), "trigger": trigger, "budget": conf["budget"],
           "cost": 0.0, "stopped": None, "where": target.get("where"), "did": [], "left": list(left)}

    prep = None
    if todo:
        prep = agent.call("before", target, todo, False) or {}
        if isinstance(prep, str):
            prep = {"skip": prep}
        if prep and prep.get("skip"):
            run["stopped"] = prep["skip"]
            run["left"] += _left(todo, prep["skip"])
            todo = []
        elif prep and prep.get("where"):
            run["where"] = prep["where"]
    agent.log("start %s: %d to run, %d not run%s" % (
        tid, len(todo), len(left), (" (%s)" % run["stopped"]) if run["stopped"] else ""))
    attempts = []

    try:
        for n, item in enumerate(todo):
            at = _now()
            opts = options(agent, item, target, conf)
            stop = None
            if run["cost"] + float(opts["budget"]) > budget + 1e-9:
                stop = "the night's budget of $%.2f would not cover another item" % budget
            elif trigger == "schedule" and at.hour not in conf["hours"]:
                stop = "the scheduled hours ended"
            elif trigger == "schedule" and fences.stop_before(at, opts["budget"]):
                stop = fences.stop_before(at, opts["budget"])
            else:
                stop = agent.call("should_stop", target, run)
            if stop:
                run["stopped"] = stop
                run["left"] += _left(todo[n:], stop)
                agent.log("stopped %s: %s" % (tid, stop))
                break

            try:
                agent.move(item, {"state": "doing", "owner": agent.id}, m)
            except stream.QueueError as exc:
                run["left"].append({"id": item.get("id") or "", "title": item["title"], "kind": "busy",
                                    "why": "the queue was being written by something else (%s)" % exc})
                continue

            agent.log("  > %s" % item["title"])
            agent.call("starting", item, target, opts)
            began = _now()
            res = claude.run(agent.hooks.prompt(item, target), opts)
            run["cost"] += res.cost
            fences.record(agent.id, tid, item["title"], res.cost, _now())

            landed = None
            if not res.error:
                try:
                    landed = agent.hooks.land(item, res.as_dict(), target) or {}
                except Exception as exc:  # noqa: BLE001 - a hook's bug is one failed item, not a dead run
                    res.error, res.kind = "%s: %s" % (type(exc).__name__, exc), "land"
            else:
                agent.call("failed", item, dict(res.as_dict(), error=res.error, kind=res.kind), target)

            iid = item.get("id") or item["title"]
            row = ledger.get(iid) or {}
            entry = {"id": iid, "title": item["title"], "when": began.isoformat(timespec="seconds"),
                     "cost": round(res.cost, 4), "session": res.session}

            if res.error and res.kind == "limit":
                agent.move(item, {"state": "ready", "owner": agent.id}, m)
                why, _ = claude.explain(res, opts)
                run["stopped"] = why
                run["left"] += _left(todo[n:], why)
                agent.log("stopped %s: %s" % (tid, why))
                break

            # A failure is Claude's (res.error) or the agent's own verdict on what came back
            # (landed["failed"]: tests went red, it wrote somewhere it may not).
            failure = res.error or (landed or {}).get("failed")
            if failure:
                if res.error:
                    why, fix = claude.explain(res, opts)
                    said = agent.call("explain", res.error, res.kind)
                    if said:
                        why, fix = said
                else:
                    why, fix = landed["failed"], landed.get("fix") or ""
                fails = int(row.get("fails") or 0) + 1
                set_aside = fails >= MAX_FAILS or bool((landed or {}).get("set_aside"))
                if set_aside:
                    agent.move(item, {"state": "blocked", "owner": "me", "needs_you": True,
                                      "feedback": "Failed %d time%s. Last: %s" % (fails, "" if fails == 1 else "s", why)},
                               m)
                else:
                    agent.move(item, {"state": "ready", "owner": agent.id}, m)
                ledger[iid] = dict(row, title=item["title"], fails=fails, fingerprint=fingerprint(item),
                                   last="blocked" if set_aside else "failed", why=why, when=entry["when"],
                                   error=(res.error or "")[:300], ref=(landed or {}).get("ref"))
                agent.save_ledger(tid, ledger)
                run["did"].append(dict(entry, outcome="failed", tone="bad",
                                       label=(landed or {}).get("label") or "failed", why=why, fix=fix,
                                       fails=fails, set_aside=set_aside, kind=res.kind or "verdict",
                                       ref=(landed or {}).get("ref"), detail=(landed or {}).get("detail")))
                agent.log("  failed %s · %s" % (item["title"], why))
                if (landed or {}).get("stop"):
                    run["stopped"] = landed["stop"]
                    run["left"] += _left(todo[n + 1:], landed["stop"])
                    agent.log("stopped %s: %s" % (tid, run["stopped"]))
                    break
                attempts.append((False, res.kind if res.kind not in (None, "other") else why))
                if len(attempts) == 2 and not attempts[0][0] and attempts[0][1] == attempts[1][1]:
                    run["stopped"] = "the first two items failed the same way (%s)" % why
                    run["left"] += _left(todo[n + 1:], "the first two failed the same way")
                    agent.log("stopped %s: %s" % (tid, run["stopped"]))
                    break
                continue

            changes = {"state": "review", "owner": "me", "seen": False}
            changes.update(landed.get("fields") or {})
            if landed.get("needs_you"):
                changes["needs_you"] = True
            if landed.get("feedback"):
                changes["feedback"] = landed["feedback"]
            agent.move(item, changes, m)
            ledger[iid] = {"title": item["title"], "fingerprint": fingerprint(item), "fails": 0,
                           "last": "again" if landed.get("again") else "ran", "when": entry["when"],
                           "ref": landed.get("ref"), "outcome": landed.get("label")}
            agent.save_ledger(tid, ledger)
            run["did"].append(dict(entry, outcome="ran", tone=landed.get("tone") or "good",
                                   label=landed.get("label") or "done",
                                   summary=landed.get("summary") or "done", ref=landed.get("ref"),
                                   detail=landed.get("detail")))
            agent.log("  ran %s · $%.2f" % (item["title"], res.cost))
            attempts.append((True, None))
    finally:
        # Always, even when nothing ran or before() refused: an agent that keeps
        # its own records (the planning agent's index and run.json) writes them here.
        try:
            agent.call("after", target, run)
        except Exception as exc:  # noqa: BLE001 - logged; the run record still gets written
            agent.log("%s: after() failed: %s: %s" % (tid, type(exc).__name__, exc))

    run["finished"] = _now().isoformat(timespec="seconds")
    run["cost"] = round(run["cost"], 4)
    daylog.add_run(agent.state_dir, tid, run, agent.title(target))
    daylog.prune(agent.state_dir, tid, now.date())
    ran = len([d for d in run["did"] if d["outcome"] == "ran"])
    agent.log("done %s: %d ran, %d failed, %d not run, $%.2f%s" % (
        tid, ran, len(run["did"]) - ran, len(run["left"]), run["cost"],
        " (stopped early)" if run["stopped"] else ""))
    if trigger == "schedule":
        notify(agent, target, run)
    return run
