#!/usr/bin/env python3
"""Finding the agents, and talking to them.

An agent is a folder with an `agent.json` in it, and this module is everything
known about how to reach one: where they are, how to ask one for its state, and
how to hand one a change or an action. The agents dashboard is one app built on
it; anything else that monitors agents imports the same module.

Nothing in here parses an agent's own files. `CONTRACT.md` in agents-dashboard
says why at length; the short version is that a schedule with two writers is a schedule
that will disagree with itself, so the agent stays the only thing that opens its
own config and this asks it politely over a pipe.
"""

import json
import os
import subprocess

CODE = os.path.expanduser("~/Code")

# Three levels below ~/Code, which is deep enough for `to-dos/agents/planning_agent`
# and shallow enough not to walk into anything's build output.
MAX_DEPTH = 3
SKIP = {"node_modules", ".git", "EXTERNAL", "TEMP", "__pycache__"}

# A state read shells out to git in every repo an agent serves, so it is not
# quick, but it is not minutes either. A run is started detached and answers at
# once, so it gets the short one.
STATE_TIMEOUT = 90
WRITE_TIMEOUT = 30


class AgentError(RuntimeError):
    pass


def find(root=None):
    """Every agent under ~/Code, by descriptor, sorted by name.

    Never cached. The whole file is a few hundred bytes and the walk is the
    cheap half of a page load; an agent added while the dashboard was open
    appearing only after a restart would be a worse trade than the walk.
    """
    root = root or CODE
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
        if "agent.json" not in filenames:
            continue
        try:
            agent = load(os.path.join(dirpath, "agent.json"))
        except AgentError:
            continue
        out.append(agent)
    out.sort(key=lambda a: (a["name"].lower(), a["root"]))
    _key(out, root)
    return out


# What a reference card can be. `planned` is work that does not exist yet;
# `built` is an agent that exists and has nothing to schedule.
KINDS = ("planned", "built")


def references(root=None, path=None):
    """Agents with no `agent.json`, as cards with nothing to run.

    The walk above finds an agent by its `agent.json`, which two kinds of
    folder do not have — so without this the page cannot show that the work
    exists at all, and the only agents on it are the ones already spending
    money overnight.

    `kind` says which of the two an entry is, and it is the whole of what this
    adds over version 1.5. `planned` is a folder holding a plan and nothing
    else, work that does not exist yet. `built` is an agent that is written and
    running but has no schedule to keep and no switch to flip — the to-dos
    implementing agent is the case it was added for, on 19 Sep 2026: it only
    ever runs from a session he is in, through the `do` skill, so a descriptor
    would put a Run now button on the page for the one agent that must not have
    one. Drawn as "Built · not scheduled" rather than "not built yet", which
    would be a plain lie about it.

    This is the one place the dashboard reads a file that is not an agent's own
    answer about itself, and it stays honest by being about folders that have
    no answer yet. The moment one grows an `agent.json` it is dropped from here
    and picked up by the walk instead, so the two can never both draw it and
    nothing has to be deleted by hand when a plan becomes an agent.

    A card from here carries `reference` and no commands. Everything that
    writes or starts something refuses an id it cannot find among the real
    agents, so there is no route from one of these to a run.
    """
    # The list is an app's own, so the app names it. No path is no list.
    if not path:
        return []
    root = root or CODE
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    # `references` is the key, and `planned` is what it was called while this
    # file only held the one kind. Both are read so a file written before
    # 19 Sep 2026 still draws.
    entries = data.get("references")
    if entries is None:
        entries = data.get("planned")
    for entry in (entries or []):
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        where = os.path.join(root, entry["path"])
        if os.path.exists(os.path.join(where, "agent.json")):
            continue
        name = entry.get("name") or os.path.basename(entry["path"])
        # An unrecognised kind reads as planned rather than as an error, for
        # the same reason an unrecognised status draws as none: a card that
        # reads oddly beats a card that is missing.
        kind = entry.get("kind") if entry.get("kind") in KINDS else "planned"
        out.append({
            "id": entry.get("id") or name.lower().replace(" ", "-"),
            "name": name,
            "root": where,
            "blurb": entry.get("blurb") or "",
            "cadence": entry.get("cadence") or "on demand",
            "doc": entry.get("doc") or "",
            "missing": not os.path.isdir(where),
            "reference": True,
            "kind": kind,
            "started_by": entry.get("started_by") or "",
            "targets": [],
        })
    out.sort(key=lambda a: a["name"].lower())
    for a in out:
        a["key"] = a["id"]
    return out


def _key(agents, root):
    """Give every agent something unique to be addressed by.

    An id is an agent's own name for itself, and a copied repo brings a second
    folder claiming the same one — `to-dos copy/agents/planning_agent` is the whole
    of the to-dos planning agent, descriptor included. Two cards with one id means
    a switch on either reaches whichever the walk happened to find first, which
    is how a copy gets switched off and the original comes on instead.

    So the id is the key only while it is the agent's alone. Once two folders
    claim it, both keys carry where they were found, and each agent is told the
    other's root so the page can say why it is drawing two of something.
    """
    seen = {}
    for agent in agents:
        seen.setdefault(agent["id"], []).append(agent)
    for agent_id, claimants in seen.items():
        if len(claimants) == 1:
            claimants[0]["key"] = agent_id
            continue
        for agent in claimants:
            where = os.path.relpath(agent["root"], root)
            agent["key"] = "%s@%s" % (agent_id, where)
            agent["twin"] = [o["root"] for o in claimants if o is not agent]


def load(path):
    """One descriptor, with its commands resolved to absolute working directories."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise AgentError("%s: %s" % (path, exc))
    if not isinstance(data, dict) or not data.get("id") or not data.get("name"):
        raise AgentError("%s: needs an id and a name" % path)
    here = os.path.dirname(os.path.abspath(path))
    data["root"] = here
    data["cwd"] = os.path.normpath(os.path.join(here, data.get("cwd") or "."))
    data["descriptor"] = path
    return data


def _call(agent, verb, payload=None, timeout=STATE_TIMEOUT):
    cmd = agent.get(verb)
    if not cmd:
        raise AgentError("%s has no %r command" % (agent["name"], verb))
    body = json.dumps(payload or {}) if payload is not None else ""
    try:
        proc = subprocess.run(cmd, cwd=agent["cwd"], input=body, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AgentError("%s took longer than %ds to answer" % (agent["name"], timeout))
    except OSError as exc:
        raise AgentError("could not start %s: %s" % (" ".join(cmd), exc))
    if proc.returncode != 0:
        first = (proc.stderr or proc.stdout or "").strip().split("\n")
        raise AgentError(first[-1][:300] if first and first[0] else
                         "exited %d with nothing to say" % proc.returncode)
    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        raise AgentError("answered with something that is not JSON: %s"
                         % (proc.stdout or "").strip()[:200])


def state(agent):
    """One agent's card, or a card saying why there isn't one.

    An agent that cannot answer is still drawn, because a half-finished edit to
    an agent looks exactly like this and a page that went blank for it would
    hide the one thing worth reading.
    """
    try:
        s = _call(agent, "state", payload=None)
    except AgentError as exc:
        s = {"broken": str(exc)}
    s.setdefault("id", agent["id"])
    s.setdefault("name", agent["name"])
    s["root"] = agent["root"]
    # The one document that says what this agent is, so the card can link it
    # next to the folder. Named in agent.json when it is called something else,
    # and a README beside the descriptor when it is not. Never invented: a link
    # to a file that is not there is worse than no link.
    doc = agent.get("doc") or "README.md"
    s["doc"] = doc if os.path.isfile(os.path.join(agent["root"], doc)) else ""
    # The page addresses an agent by key rather than by id, and the key is the
    # dashboard's own — an agent prints its id and knows nothing about anything
    # else claiming it — so it is stamped on here and never taken from the
    # answer.
    s["key"] = agent.get("key", agent["id"])
    if agent.get("twin"):
        s["twin"] = agent["twin"]
    s.setdefault("targets", [])
    return s


def apply(agent, target, changes):
    return _call(agent, "apply", {"target": target, "changes": changes},
                 timeout=WRITE_TIMEOUT)


def start(agent, action, target=None):
    return _call(agent, "run", {"action": action, "target": target},
                 timeout=WRITE_TIMEOUT)


def activity(agent, since):
    """What one agent did since a given instant, per the 1.1 contract.

    Optional, and the only command here that is. An agent written against 1.0
    has no `activity` in its descriptor and raises rather than answering, which
    is the caller's cue to say so and carry on with the agents that do — the
    report is meant to survive a third agent arriving before it has learned to
    account for itself.

    Nothing in here interprets the answer. The reporting skill in
    `~/Code/skills/personal/agents-report` is the only caller today and does the
    reading; this is the pipe, and it stays as ignorant of what a run means as
    the rest of the module is.
    """
    return _call(agent, "activity", {"since": since}, timeout=STATE_TIMEOUT)
