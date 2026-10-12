"""Daily spending ceilings: one per agent, and one across every agent on the machine.

An agent's own settings say when it may start and how much it may spend a night.
This sits above all of them, in one file, so "this agent spends at most this much
a day" and "the whole machine spends at most this much a day" are written once. When each agent runs is set per agent, on the
dashboard, and nothing here overrides it.

It fences scheduled runs only. A run started by hand (`--now`, or Run now on the
dashboard) is someone asking for it, so it goes ahead, and its spend still counts
towards the day.

    ~/Code/AGENTS/fences.json      or the path in $AGENTS_FENCES
    {"daily_budget": 20.0, "agent_budgets": {"plan-agent": 2.0, "implement-agent": 5.0}}

An agent stops at its own budget, and every agent stops at `daily_budget`, so
both apply. A missing file, a missing key, or an agent not named in
`agent_budgets` fences nothing.
Spend is kept in `spend/YYYY-MM-DD.jsonl` beside the file, one line per item run.
Agents run in parallel, so the ceiling is checked before each item and the day can
overshoot it by at most one item per agent running at that moment.
"""

import datetime as dt
import json
import os

DEFAULT = "~/Code/AGENTS/fences.json"


def path():
    return os.path.expanduser(os.environ.get("AGENTS_FENCES") or DEFAULT)


def load():
    try:
        with open(path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _spend_file(day):
    return os.path.join(os.path.dirname(path()), "spend", "%s.jsonl" % day.isoformat())


def spent(day, agent_id=None):
    """The day's spend across every agent, or one agent's when `agent_id` is given."""
    total = 0.0
    try:
        with open(_spend_file(day), encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    if agent_id is None or rec.get("agent") == agent_id:
                        total += float(rec.get("cost") or 0)
                except (ValueError, AttributeError):
                    continue
    except OSError:
        pass
    return total


def record(agent_id, target_id, title, cost, now):
    if not cost:
        return
    where = _spend_file(now.date())
    os.makedirs(os.path.dirname(where), exist_ok=True)
    line = json.dumps({"when": now.isoformat(timespec="seconds"), "agent": agent_id,
                       "target": target_id, "item": title, "cost": round(cost, 4)})
    with open(where, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def left(now, f=None):
    """What the machine may still spend today, or None when there is no ceiling."""
    f = load() if f is None else f
    ceiling = f.get("daily_budget")
    if ceiling is None:
        return None
    return max(0.0, float(ceiling) - spent(now.date()))


def agent_budget(agent_id, f=None):
    """The agent's own daily budget, or None when it has none."""
    f = load() if f is None else f
    budgets = f.get("agent_budgets")
    if not isinstance(budgets, dict) or budgets.get(agent_id) is None:
        return None
    try:
        return float(budgets[agent_id])
    except (TypeError, ValueError):
        return None


def agent_left(agent_id, now, f=None):
    """What one agent may still spend today, or None when it has no budget of its own."""
    ceiling = agent_budget(agent_id, f)
    if ceiling is None:
        return None
    return max(0.0, ceiling - spent(now.date(), agent_id))


def stop_before(now, item_budget, agent_id=None):
    """The reason a scheduled pass must stop before its next item, or None."""
    f = load()
    need = float(item_budget) - 1e-9
    if agent_id is not None:
        room = agent_left(agent_id, now, f)
        if room is not None and room < need:
            return "%s's daily budget of $%.2f would not cover another item" % (
                agent_id, agent_budget(agent_id, f))
    room = left(now, f)
    if room is not None and room < need:
        return "the machine's daily ceiling of $%.2f would not cover another item" % float(f["daily_budget"])
    return None


def prune(today, keep_days=30):
    where = os.path.join(os.path.dirname(path()), "spend")
    try:
        names = os.listdir(where)
    except OSError:
        return
    cutoff = today - dt.timedelta(days=keep_days)
    for n in names:
        try:
            if dt.date.fromisoformat(n.split(".")[0]) < cutoff:
                os.remove(os.path.join(where, n))
        except (ValueError, OSError):
            continue
