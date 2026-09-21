#!/usr/bin/env python3
"""Checks on the runner, against a fake agent and a fake `claude`.

The fake `claude` is a small script that answers according to a word in the
prompt, so each item in a test queue can succeed, fail, time out or hit the
usage limit on purpose. Nothing here spends anything.

    python3 python/test_runner.py
"""

import datetime as dt
import json
import os
import shutil
import stat
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["AGENTS_RUNNER_QUIET"] = "1"

from agents_engine import runner  # noqa: E402
from agents_engine.runner import core, daylog, lock, settings, stream  # noqa: E402

FAILED = []

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, sys
prompt = sys.argv[sys.argv.index("-p") + 1]
if "BREAK" in prompt:
    print(json.dumps({"is_error": True, "result": "Something broke inside", "total_cost_usd": 0.10}))
elif "NOAGENT" in prompt:
    print("Error: --agent 'ghost' not found. Available agents: claude", file=sys.stderr); sys.exit(1)
elif "LIMIT" in prompt:
    print(json.dumps({"is_error": True, "result": "You've hit your session limit · resets 3:45am"}))
else:
    print(json.dumps({"result": "REVIEW for " + prompt, "session_id": "s1", "total_cost_usd": 1.25}))
'''

STREAM = {
    "contract": "1.0", "id": "test-queue", "name": "Test queue",
    "container": {"kind": "doc-folder", "path": "queue/<target>"},
    "states": {"backlog": "Backlog", "ready": "To do", "doing": "Doing", "review": "Waiting for you",
               "blocked": "Blocked", "done": "Done"},
    "writer": {"who": "test-agent", "how": {"kind": "subprocess", "cwd": ".",
                                            "apply": ["python3", "run.py", "--stream-apply"]},
               "lock": "state/.queue.lock"},
}


def check(name, got, want):
    if got != want:
        FAILED.append("%s\n    got  %r\n    want %r" % (name, got, want))


def hooks_module():
    h = types.ModuleType("hooks")
    h.ID, h.NAME, h.BLURB = "test-agent", "Test agent", "a fake"
    h.targets = lambda: [{"id": "alpha", "name": "Alpha"}]
    h.stream = lambda target: "queue/stream.json"
    h.eligible = lambda item, target: None if item["fields"].get("angle") else "no angle given"
    h.prompt = lambda item, target: item["body"].strip()
    h.options = lambda item, target: {"tools": ["Read"], "budget": 2.0, "timeout": 30}

    def land(item, result, target):
        return {"ref": "out/%s.md" % item["id"], "summary": "written", "fields": {"review": "out/x.md"}}
    h.land = land
    return h


def make_agent():
    root = tempfile.mkdtemp(prefix="runner-test-")
    os.makedirs(os.path.join(root, "queue", "alpha"))
    with open(os.path.join(root, "queue", "stream.json"), "w") as fh:
        json.dump(STREAM, fh)
    fake = os.path.join(root, "claude")
    with open(fake, "w") as fh:
        fh.write(FAKE_CLAUDE)
    os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
    os.environ["AGENTS_RUNNER_CLAUDE"] = fake
    return core.Agent(hooks_module(), root), root


def add(root, name, body, angle="yes", **fields):
    lines = ["---", "state: ready", "owner: test-agent"]
    if angle:
        lines.append("angle: %s" % angle)
    lines += ["%s: %s" % kv for kv in fields.items()]
    with open(os.path.join(root, "queue", "alpha", name), "w") as fh:
        fh.write("\n".join(lines) + "\n---\n# %s\n\n%s\n" % (name[:-3], body))


def fields_of(root, name):
    return stream.read(os.path.join(root, "queue", "alpha", name))["fields"]


def day_md(agent, when):
    with open(os.path.join(agent.state_dir, "alpha", "runs", "%s.md" % when.date().isoformat())) as fh:
        return fh.read()


def test_happy_path_and_log():
    agent, root = make_agent()
    add(root, "one.md", "review this page")
    add(root, "two.md", "please BREAK")
    add(root, "three.md", "no angle here", angle=None)
    target = agent.target("alpha")
    run = core.run_target(agent, target, trigger="manual")

    check("one moved to review", fields_of(root, "one.md").get("state"), "review")
    check("one owned by me", fields_of(root, "one.md").get("owner"), "me")
    check("one got its landed field", fields_of(root, "one.md").get("review"), "out/x.md")
    check("one got an id", len(fields_of(root, "one.md").get("id", "")), 6)
    check("two back to ready after one failure", fields_of(root, "two.md").get("state"), "ready")
    check("three untouched", fields_of(root, "three.md").get("state"), "ready")
    check("cost adds up", round(run["cost"], 2), 1.35)

    md = day_md(agent, dt.datetime.now())
    check("log has Ran", "## Ran" in md and "**one** · written" in md, True)
    check("log has Not run with reason", "**three** · no angle given" in md, True)
    check("log has Failed with count", "**two**" in md and "Failed 1 of 3" in md, True)
    check("log counts line", "1 ran · 1 not run · 1 failed · $1.35 of $6.00" in md, True)

    # Second pass the same day: one is not ready any more, two fails again.
    run2 = core.run_target(agent, target, trigger="manual")
    check("second run only retried two", [d["title"] for d in run2["did"]], ["two"])
    md = day_md(agent, dt.datetime.now())
    check("one day, one file, failures counted", "Failed 2 of 3" in md, True)
    shutil.rmtree(root)


def test_unchanged_is_skipped_and_feedback_reruns():
    agent, root = make_agent()
    add(root, "one.md", "review this page")
    target = agent.target("alpha")
    core.run_target(agent, target, trigger="manual")
    item = stream.read(os.path.join(root, "queue", "alpha", "one.md"))
    stream.write(item, {"state": "ready", "owner": "test-agent"})
    todo, left, _ = core.select(agent, target)
    check("moved back unchanged is skipped", [l["kind"] for l in left], ["unchanged"])
    stream.write(item, {"feedback": "look at the empty state too"})
    todo, left, _ = core.select(agent, target)
    check("sent back with a reason runs again", [t["title"] for t in todo], ["one"])
    shutil.rmtree(root)


def test_three_failures_block():
    agent, root = make_agent()
    add(root, "bad.md", "BREAK me")
    target = agent.target("alpha")
    for _ in range(3):
        core.run_target(agent, target, trigger="manual")
    f = fields_of(root, "bad.md")
    check("blocked after three", f.get("state"), "blocked")
    check("owned by me", f.get("owner"), "me")
    check("needs you", f.get("needs_you"), "yes")
    check("says why", f.get("feedback", "").startswith("Failed 3 times"), True)
    check("log says set aside", "now Blocked and waiting on you" in day_md(agent, dt.datetime.now()), True)
    shutil.rmtree(root)


def test_same_failure_twice_stops():
    agent, root = make_agent()
    for n in ("a", "b", "c"):
        add(root, "%s.md" % n, "NOAGENT %s" % n, created="2026-09-0%d" % "abc".index(n))
    run = core.run_target(agent, agent.target("alpha"), trigger="manual")
    check("only two attempted", len(run["did"]), 2)
    check("stopped for the same failure", "failed the same way" in (run["stopped"] or ""), True)
    check("plain reading of a missing agent", run["did"][0]["why"], "the agent definition 'ghost' is missing")
    check("third left, not reached", [l["title"] for l in run["left"]], ["c"])
    shutil.rmtree(root)


def test_limit_stops_and_puts_back():
    agent, root = make_agent()
    add(root, "a.md", "LIMIT please", created="2026-09-01")
    add(root, "b.md", "fine", created="2026-09-02")
    run = core.run_target(agent, agent.target("alpha"), trigger="manual")
    check("limit stops the run", "usage limit, resets 3:45am" in (run["stopped"] or ""), True)
    check("limited item back to ready", fields_of(root, "a.md").get("state"), "ready")
    check("nothing counted as failed", run["did"], [])
    shutil.rmtree(root)


def test_budget_stops():
    agent, root = make_agent()
    settings.save(agent.state_dir, agent.hooks, "alpha", {"budget": 3})
    add(root, "a.md", "one", created="2026-09-01")
    add(root, "b.md", "two", created="2026-09-02")
    run = core.run_target(agent, agent.target("alpha"), trigger="manual")
    check("stopped by budget after one", len(run["did"]), 1)
    check("budget reason", "budget of $3.00 would not cover" in (run["stopped"] or ""), True)
    shutil.rmtree(root)


def test_wake_respects_switch_and_hours():
    agent, root = make_agent()
    add(root, "a.md", "one")
    now = dt.datetime(2026, 9, 21, 2, 15).astimezone()
    runner.wake(agent, now=now)
    check("off: nothing ran", fields_of(root, "a.md").get("state"), "ready")
    settings.save(agent.state_dir, agent.hooks, "alpha", {"on": True, "hours": [3]})
    runner.wake(agent, now=now)
    check("wrong hour: nothing ran", fields_of(root, "a.md").get("state"), "ready")
    data = daylog.load(agent.state_dir, "alpha", now.date())
    check("idle wake recorded", data["wakes"].get("02"), "idle")
    shutil.rmtree(root)


def test_lock():
    root = tempfile.mkdtemp()
    path = os.path.join(root, "t", ".lock")
    check("first takes it", lock.acquire(path)[0], True)
    check("second refused while alive", lock.acquire(path)[0], False)
    with open(os.path.join(path, "pid"), "w") as fh:
        fh.write("999999")
    taken, note = lock.acquire(path)
    check("dead holder cleared", (taken, "stale" in (note or "")), (True, True))
    lock.release(path)
    check("released", os.path.exists(path), False)
    shutil.rmtree(root)


def test_apply_and_state_and_activity():
    agent, root = make_agent()
    check("bad hour refused", runner.apply(agent, {"target": "alpha", "changes": {"hours": [25]}})["ok"], False)
    check("unknown setting refused", runner.apply(agent, {"target": "alpha", "changes": {"x": 1}})["ok"], False)
    check("good change", runner.apply(agent, {"target": "alpha", "changes": {"on": True, "hours": [2, 1]}}),
          {"ok": True})
    check("hours sorted", settings.load(agent.state_dir, agent.hooks, "alpha")["hours"], [1, 2])
    add(root, "a.md", "one")
    add(root, "b.md", "BREAK")
    core.run_target(agent, agent.target("alpha"), trigger="manual")
    card = runner.state(agent)
    check("card tone bad after a failure", card["tone"], "bad")
    check("card has one target", [t["id"] for t in card["targets"]], ["alpha"])
    check("review counted", card["targets"][0]["counts"][1]["n"], 1)
    act = runner.activity(agent, {"since": (dt.datetime.now().astimezone() - dt.timedelta(hours=1)).isoformat()})
    check("activity has the run", len(act["runs"]), 1)
    check("activity did", sorted(d["outcome"] for d in act["runs"][0]["did"]), ["failed", "ran"])
    shutil.rmtree(root)


def test_stream_apply():
    agent, root = make_agent()
    add(root, "a.md", "one", state="review")
    out = runner.stream_apply(agent, {"item": {"group": "alpha", "name": "a.md"}, "to": "ready",
                                      "owner": "test-agent", "reason": "Check mobile too."})
    check("stream apply ok", out["ok"], True)
    check("feedback written", fields_of(root, "a.md").get("feedback"), "Check mobile too.")
    check("unknown state refused", runner.stream_apply(
        agent, {"item": {"group": "alpha", "name": "a.md"}, "to": "nowhere"})["ok"], False)
    shutil.rmtree(root)


def read_only_agent(entries, calls):
    """An agent over a queue it does not own: items come from a hook and nothing is written back."""
    agent, root = make_agent()
    h = agent.hooks
    del h.stream
    h.items = lambda target: [{"id": e, "title": e, "fields": {}, "body": e} for e in entries]
    h.eligible = lambda item, target: None

    def before(target, todo, dry):
        calls.append(("before", dry, len(todo)))
        return {"where": "improve/today"}
    h.before = before
    h.after = lambda target, run: calls.append(("after", len(run["did"])))

    def land(item, result, target):
        if "RED" in item["body"]:
            return {"failed": "2 of 3 tests failed", "label": "tests failed", "ref": "abc123"}
        if "PROTECTED" in item["body"]:
            return {"failed": "wrote into data/", "set_aside": True, "label": "refused"}
        if "RESTART" in item["body"]:
            return {"label": "needs a restart", "again": True}
        return {"label": "built", "ref": "def456", "summary": "built it"}
    h.land = land
    agent = core.Agent(h, root)
    return agent, root


def test_read_only_queue():
    calls = []
    agent, root = read_only_agent(["good", "RED one", "PROTECTED one", "RESTART one"], calls)
    target = agent.target("alpha")
    run = core.run_target(agent, target, trigger="manual")
    check("before then after", [c[0] for c in calls], ["before", "after"])
    check("where comes from before", run["where"], "improve/today")
    outcomes = {d["title"]: (d["outcome"], d.get("set_aside")) for d in run["did"]}
    check("verdicts", outcomes, {"good": ("ran", None), "RED one": ("failed", False),
                                 "PROTECTED one": ("failed", True), "RESTART one": ("ran", None)})
    check("no files written back", sorted(os.listdir(os.path.join(root, "queue", "alpha"))), [])
    todo, left, m = core.select(agent, target)
    check("next time: red and restart again, good unchanged, protected set aside",
          (sorted(t["title"] for t in todo), sorted((l["title"], l["kind"]) for l in left)),
          (["RED one", "RESTART one"], [("PROTECTED one", "blocked"), ("good", "unchanged")]))
    card = runner.state(agent)["targets"][0]
    check("card counts the set-aside one as blocked", card["counts"][2]["n"], 1)
    shutil.rmtree(root)


def test_before_can_skip():
    calls = []
    agent, root = read_only_agent(["good"], calls)
    agent.hooks.before = lambda target, todo, dry: "working tree not clean"
    run = core.run_target(agent, agent.target("alpha"), trigger="manual")
    check("skipped with reason", run["stopped"], "working tree not clean")
    check("item listed as not reached", [l["why"] for l in run["left"]], ["not reached: working tree not clean"])
    check("after not called when skipped", calls, [])
    shutil.rmtree(root)


def test_agent_budget_shared_across_targets():
    agent, root = make_agent()
    os.makedirs(os.path.join(root, "queue", "beta"))
    agent.hooks.targets = lambda: [{"id": "alpha"}, {"id": "beta"}]
    agent.hooks.agent_budget = lambda: 3.0
    for t in ("alpha", "beta"):
        settings.save(agent.state_dir, agent.hooks, t, {"on": True, "hours": [2]})
    add(root, "a.md", "one")
    with open(os.path.join(root, "queue", "beta", "b.md"), "w") as fh:
        fh.write("---\nstate: ready\nangle: yes\n---\n# b\n\ntwo\n")
    runner.wake(agent, now=dt.datetime(2026, 9, 21, 2, 15).astimezone())
    beta = stream.read(os.path.join(root, "queue", "beta", "b.md"))["fields"]["state"]
    check("alpha spent 1.25, so beta's $2 item does not fit in the $3 left", beta, "ready")
    shutil.rmtree(root)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILED:
        print("%d failed:\n  %s" % (len(FAILED), "\n  ".join(FAILED)))
        sys.exit(1)
    print("runner: all passed")
