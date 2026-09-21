"""The daily log: one readable file per target per day, and the JSON behind it.

`runs/YYYY-MM-DD.json` holds the facts, and `activity` reads it.
`runs/YYYY-MM-DD.md` is rendered from it on every write and is the one meant to
be opened in the morning. It answers three questions in order: what ran, what
did not, and what failed. Hours where nothing was due collapse into one line.

A second run on the same day is added to the same file. The planning agent once
wrote a second run's index over the first, and the first night's plans sat in
the folder unlinked, which is why the day is the unit here and not the run.
"""

import datetime as dt
import json
import os

KEEP_DAYS = 30
MAX_FAILS = 3


def slug(target_id):
    """A target id as one folder name. Repo names such as `AGENTS/ux-agent` hold a slash."""
    return target_id.replace("/", "--")


def folder(state_dir, target_id):
    return os.path.join(state_dir, slug(target_id), "runs")


def _path(state_dir, target_id, day, ext):
    return os.path.join(folder(state_dir, target_id), "%s.%s" % (day.isoformat(), ext))


def load(state_dir, target_id, day):
    try:
        with open(_path(state_dir, target_id, day, "json"), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("runs", [])
            data.setdefault("wakes", {})
            return data
    except (OSError, ValueError):
        pass
    return {"date": day.isoformat(), "target": target_id, "runs": [], "wakes": {}}


def save(state_dir, target_id, day, data, title):
    os.makedirs(folder(state_dir, target_id), exist_ok=True)
    for ext, body in (("json", json.dumps(data, indent=2) + "\n"), ("md", render(data, title))):
        path = _path(state_dir, target_id, day, ext)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, path)


def add_wake(state_dir, target_id, now, what, title):
    """`what` is 'ran', 'idle' or 'off'. One mark per hour, the most useful kept."""
    day = now.date()
    data = load(state_dir, target_id, day)
    hour = "%02d" % now.hour
    rank = {"off": 0, "idle": 1, "busy": 2, "ran": 3}
    if rank.get(what, 0) >= rank.get(data["wakes"].get(hour), -1):
        data["wakes"][hour] = what
    save(state_dir, target_id, day, data, title)


def add_run(state_dir, target_id, run, title):
    day = dt.datetime.fromisoformat(run["started"]).date()
    data = load(state_dir, target_id, day)
    data["runs"].append(run)
    save(state_dir, target_id, day, data, title)


def days(state_dir, target_id, since_day, until_day):
    out, d = [], since_day
    while d <= until_day:
        if os.path.exists(_path(state_dir, target_id, d, "json")):
            out.append(load(state_dir, target_id, d))
        d += dt.timedelta(days=1)
    return out


def latest(state_dir, target_id):
    """The most recent day file that holds a run, or None."""
    where = folder(state_dir, target_id)
    try:
        names = sorted((n for n in os.listdir(where) if n.endswith(".json")), reverse=True)
    except OSError:
        return None
    for name in names:
        try:
            data = load(state_dir, target_id, dt.date.fromisoformat(name[:-5]))
        except ValueError:
            continue
        if data["runs"]:
            return data
    return None


def prune(state_dir, target_id, today):
    where = folder(state_dir, target_id)
    cutoff = today - dt.timedelta(days=KEEP_DAYS)
    try:
        names = os.listdir(where)
    except OSError:
        return
    for name in names:
        try:
            if dt.date.fromisoformat(name[:10]) < cutoff:
                os.remove(os.path.join(where, name))
        except (ValueError, OSError):
            continue


def _hm(iso):
    try:
        return dt.datetime.fromisoformat(iso).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def _ranges(hours):
    """['00','01','03'] -> '00:00–01:00, 03:00'."""
    hs = sorted(int(h) for h in hours)
    out, start, prev = [], None, None
    for h in hs + [None]:
        if start is None:
            start = prev = h
        elif h is not None and h == prev + 1:
            prev = h
        else:
            out.append("%02d:00" % start if start == prev else "%02d:00–%02d:00" % (start, prev))
            start = prev = h
    return ", ".join(out)


def merged(data):
    """The day as one account: each item once, in the section its latest outcome puts it."""
    did, left, stopped, cost = {}, {}, [], 0.0
    for run in data["runs"]:
        cost += run.get("cost") or 0.0
        if run.get("stopped"):
            stopped.append("%s: %s" % (_hm(run.get("started")), run["stopped"]))
        for d in run.get("did") or []:
            key = d.get("id") or d.get("title")
            prior = did.get(key)
            if prior and prior["outcome"] == "failed" and d["outcome"] == "ran":
                d = dict(d, earlier="failed earlier today, then ran")
            did[key] = d
        for l in run.get("left") or []:
            left[l.get("id") or l.get("title")] = l
    left = {k: v for k, v in left.items() if k not in did}
    ran = [d for d in did.values() if d["outcome"] == "ran"]
    failed = [d for d in did.values() if d["outcome"] == "failed"]
    return ran, list(left.values()), failed, stopped, cost


def render(data, title):
    day = dt.date.fromisoformat(data["date"])
    ran, left, failed, stopped, cost = merged(data)
    budget = data["runs"][-1].get("budget") if data["runs"] else None
    out = ["# %s · %s" % (title, day.strftime("%a %-d %b %Y")), ""]
    if data["runs"]:
        line = "%d ran · %d not run · %d failed · $%.2f" % (len(ran), len(left), len(failed), cost)
        if budget is not None:
            line += " of $%.2f" % float(budget)
        out.append(line)
        for s in stopped:
            out.append("")
            out.append("Stopped early at %s" % s)
    else:
        out.append("Nothing ran today.")

    if ran:
        out += ["", "## Ran"]
        for d in ran:
            head = "- **%s** · %s · $%.2f · %s" % (d["title"], d.get("summary") or "done",
                                                   d.get("cost") or 0.0, _hm(d.get("when")))
            out.append(head)
            for extra in (d.get("ref"), d.get("detail"), d.get("earlier")):
                if extra:
                    out.append("  %s" % extra)

    if left:
        unchanged = [l for l in left if l.get("kind") == "unchanged"]
        others = [l for l in left if l.get("kind") != "unchanged"]
        out += ["", "## Not run"]
        for l in others:
            out.append("- **%s** · %s" % (l["title"], l["why"]))
        if unchanged:
            out.append("- Unchanged since they last ran: %s" % ", ".join(l["title"] for l in unchanged))

    if failed:
        out += ["", "## Failed"]
        for d in failed:
            line = "- **%s** · %s · %s." % (d["title"], _hm(d.get("when")), d.get("why") or "failed")
            if d.get("fix"):
                line += " %s" % d["fix"]
            fails = d.get("fails") or 1
            if d.get("set_aside") and fails >= MAX_FAILS:
                line += " Failed %d times, so it is now Blocked and waiting on you." % fails
            elif d.get("set_aside"):
                line += " Set aside until it changes or you look at it."
            else:
                line += " Failed %d of %d before it is set aside." % (fails, MAX_FAILS)
            out.append(line)

    wakes = data.get("wakes") or {}
    if wakes:
        ran_h = [h for h, w in wakes.items() if w == "ran"]
        busy_h = [h for h, w in wakes.items() if w == "busy"]
        idle_h = [h for h, w in wakes.items() if w in ("idle", "off")]
        parts = []
        if ran_h:
            parts.append("Ran at %s." % _ranges(ran_h))
        if busy_h:
            parts.append("Still busy from an earlier run at %s." % _ranges(busy_h))
        if idle_h:
            parts.append("Nothing scheduled at %s." % _ranges(idle_h))
        manual = [r for r in data["runs"] if r.get("trigger") == "manual"]
        if manual:
            parts.append("Run by hand at %s." % ", ".join(_hm(r["started"]) for r in manual))
        out += ["", "## Wakes", " ".join(parts)]
    elif any(r.get("trigger") == "manual" for r in data["runs"]):
        out += ["", "## Wakes", "Run by hand at %s." % ", ".join(
            _hm(r["started"]) for r in data["runs"] if r.get("trigger") == "manual")]
    return "\n".join(out) + "\n"
