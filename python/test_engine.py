#!/usr/bin/env python3
"""Checks on the engine, against fake agents rather than the real ones.

Every test here builds its own agents on disk — a shell script that prints a
fixed blob of JSON is a perfectly good agent as far as this dashboard is
concerned, and that is the claim worth testing. Running against the two real
ones would test them instead, and would spend money the first time somebody
pressed the wrong thing.

    python3 python/test_engine.py
"""

import json
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents_engine import discover, routes  # noqa: E402

FAILED = []


def check(name, got, want):
    if got != want:
        FAILED.append("%s\n    got  %r\n    want %r" % (name, got, want))


def fake_agent(root, agent_id, name, state, extra=None, at=None):
    """One agent on disk: a descriptor, and a script that prints `state`.

    Python rather than bash, so it runs the same way on any machine, and a real
    subprocess rather than a monkeypatch, because the thing being checked is
    that a subprocess is all an agent has to be.
    """
    folder = os.path.join(root, at or agent_id)
    os.makedirs(folder, exist_ok=True)
    script = os.path.join(folder, "run_agent.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write("import json, sys\n")
        fh.write("STATE = %r\n" % json.dumps(state))
        fh.write("if '--state' in sys.argv:\n")
        fh.write("    print(STATE)\n")
        fh.write("else:\n")
        fh.write("    body = json.loads(sys.stdin.read() or '{}')\n")
        fh.write("    print(json.dumps({'ok': True, 'saw': body}))\n")
    os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)

    desc = {"contract": "1.0", "id": agent_id, "name": name, "cwd": ".",
            "state": [sys.executable, "run_agent.py", "--state"],
            "apply": [sys.executable, "run_agent.py", "--apply"],
            "run": [sys.executable, "run_agent.py", "--run"]}
    desc.update(extra or {})
    with open(os.path.join(folder, "agent.json"), "w", encoding="utf-8") as fh:
        json.dump(desc, fh)
    return folder


def target(**kw):
    out = {"id": "t1", "name": "one", "on": True, "hours": [3, 4]}
    out.update(kw)
    return out


def test_discovery():
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "b-agent", "Bravo", {"targets": []})
        fake_agent(root, "a-agent", "Alpha", {"targets": []})
        # Three levels down is reachable, which is what the Plan agent
        # needs: it lives at to-dos/agents/plan-agent.
        fake_agent(root, "deep", "Deep", {"targets": []}, at="one/two/three")
        # Four is not, and neither is anything inside the folders that are
        # always full of other people's code.
        fake_agent(root, "toodeep", "Too deep", {"targets": []}, at="a/b/c/d")
        fake_agent(root, "vendored", "Vendored", {"targets": []},
                   at="node_modules/some-package")

        found = discover.find(root)
        check("agents come back sorted by name",
              [a["name"] for a in found], ["Alpha", "Bravo", "Deep"])
        check("cwd is absolute", os.path.isabs(found[0]["cwd"]), True)

        # A descriptor missing the two required keys is not an agent. Skipped
        # rather than raised: one broken file should not empty the page.
        os.makedirs(os.path.join(root, "junk"))
        with open(os.path.join(root, "junk", "agent.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        check("a descriptor that will not parse is skipped",
              len(discover.find(root)), 3)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_broken_agent():
    """An agent that cannot answer is a card, not an exception.

    This is the case that turns up most often in practice, because it is what a
    half-finished edit to an agent looks like, and a page that went blank for it
    would hide the one thing worth reading.
    """
    root = tempfile.mkdtemp()
    try:
        folder = fake_agent(root, "ok-agent", "Fine", {"targets": [target()]})
        broken = fake_agent(root, "bad-agent", "Broken", {"targets": []})
        with open(os.path.join(broken, "run_agent.py"), "w", encoding="utf-8") as fh:
            fh.write("import sys\nsys.stderr.write('boom\\n')\nsys.exit(1)\n")
        noise = fake_agent(root, "noisy-agent", "Noisy", {"targets": []})
        with open(os.path.join(noise, "run_agent.py"), "w", encoding="utf-8") as fh:
            fh.write("print('not json')\n")

        cards = {a["name"]: discover.state(a) for a in discover.find(root)}
        check("a healthy agent has no broken flag", cards["Fine"].get("broken"), None)
        check("a failing one is reported with its own last line",
              cards["Broken"]["broken"], "boom")
        check("and still has an empty target list to draw",
              cards["Broken"]["targets"], [])
        check("one that prints rubbish says so",
              "not JSON" in cards["Noisy"]["broken"], True)
        check("the healthy one is untouched by either",
              len(cards["Fine"]["targets"]), 1)
        assert folder
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_strip():
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "a1", "One", {
            "job": {"loaded": True, "installed": True},
            "window": {"action": "ride", "why": "open until 04:00"},
            "stats": [{"k": "Buildable now", "v": "7", "w": "nothing blocking"}],
            "targets": [target(id="x", name="x", on=True),
                        target(id="y", name="y", on=False)]})
        fake_agent(root, "a2", "Two", {
            "job": {"loaded": False, "installed": True},
            "targets": [target(id="z", name="z", on=True)]})

        s = routes.state_view(root)
        strip = {c["k"]: c for c in s["strip"]}
        check("targets on is counted across every agent",
              strip["Agents on"]["v"], "2 of 3")
        check("and names them", strip["Agents on"]["w"], "x, z")
        check("a scheduler that is not loaded is reported",
              strip["Schedulers"]["v"], "1 of 2")
        check("and reads as bad", strip["Schedulers"]["cls"], "bad")
        check("an agent's own stat is carried through",
              strip["Buildable now"]["v"], "7")
        check("the window comes from the agent that reported one",
              strip["Usage window"]["v"], "RIDE")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_window_scope():
    """A window marked `self` is not quoted for the account while another exists.

    The Plan agent's copy of the window arithmetic short-circuits on its
    own hours, so at two in the afternoon it says STOP about a schedule while
    meaning nothing about the account. Quoting that in the strip would report
    the account as spent when it is not.
    """
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "selfish", "Selfish", {
            "window": {"action": "stop", "why": "outside its own hours", "scope": "self"},
            "targets": []})
        fake_agent(root, "honest", "Honest", {
            "window": {"action": "ride", "why": "open until 04:00"},
            "targets": []})
        strip = {c["k"]: c for c in routes.state_view(root)["strip"]}
        check("the account-scoped window wins", strip["Usage window"]["v"], "RIDE")

        # On its own, a self-scoped answer is better than none.
        shutil.rmtree(os.path.join(root, "honest"))
        strip = {c["k"]: c for c in routes.state_view(root)["strip"]}
        check("a self-scoped one is used when it is all there is",
              strip["Usage window"]["v"], "STOP")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_boundaries():
    """The 1.4 field: where the windows opened, off the same window the strip quotes.

    One list for the page rather than one per agent, because where a window
    opened is a fact about the account and two panels disagreeing about it would
    be two facts. The half worth testing is the absence: every agent on this
    machine predates the field, so a state with no boundaries anywhere has to
    come back as an empty list rather than as a missing key the page then has to
    guard against.
    """
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "quiet", "Quiet", {"targets": [target()]})
        check("an agent that sends no window has no boundaries",
              routes.state_view(root)["boundaries"], [])

        fake_agent(root, "teller", "Teller", {
            "window": {"action": "ride", "why": "open until 06:12",
                       "boundaries": [{"at": "2026-09-12T21:12:00+01:00",
                                       "why": "the limit's own reset time"},
                                      {"why": "no instant on it at all"}]},
            "targets": []})
        out = routes.state_view(root)["boundaries"]
        check("a boundary is carried through whole",
              out, [{"at": "2026-09-12T21:12:00+01:00",
                     "why": "the limit's own reset time"}])

        # A window marked `self` is not the account's, and the marks down the
        # track are the account's, so the two choices have to be the one choice.
        fake_agent(root, "selfish", "Selfish", {
            "window": {"action": "stop", "why": "outside its own hours", "scope": "self",
                       "boundaries": [{"at": "2026-09-12T03:00:00+01:00"}]},
            "targets": []})
        s = routes.state_view(root)
        check("the marks come off the same window the strip quotes",
              [b["at"] for b in s["boundaries"]], ["2026-09-12T21:12:00+01:00"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_routing():
    """A change and an action reach the right agent, whole and unedited."""
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "a1", "One", {"targets": [target()]})
        agent = discover.find(root)[0]

        out = discover.apply(agent, "t1", {"hours": [1, 2, 3]})
        check("apply is passed straight through",
              out["saw"], {"target": "t1", "changes": {"hours": [1, 2, 3]}})

        out = discover.start(agent, "dry", None)
        check("so is an agent-level action",
              out["saw"], {"action": "dry", "target": None})

        # A descriptor with no `apply` is a read-only agent, and asking it to
        # write is an error here rather than a silent no-op there.
        del agent["apply"]
        try:
            discover.apply(agent, "t1", {"on": False})
            check("a missing command raises", True, False)
        except discover.AgentError as exc:
            check("a missing command raises", "no 'apply' command" in str(exc), True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_refusal():
    """An agent's own refusal reaches the page as its own sentence.

    "07:00 is inside the working day" is the whole explanation, and a 400 with
    nothing on it is none of it.
    """
    root = tempfile.mkdtemp()
    try:
        folder = fake_agent(root, "picky", "Picky", {"targets": [target()]})
        with open(os.path.join(folder, "run_agent.py"), "w", encoding="utf-8") as fh:
            fh.write("import json\n")
            fh.write("print(json.dumps({'ok': False, 'error': 'no such hour'}))\n")
        agent = discover.find(root)[0]
        out = discover.apply(agent, "t1", {"hours": [7]})
        check("a refusal comes back intact", out, {"ok": False, "error": "no such hour"})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_activity():
    """The 1.1 command: a window in, what the agent did in it out.

    Two halves. An agent that has it is handed the window and answers, and an
    agent that has not — every agent written before September 2026 — raises
    rather than being guessed at, which is what lets the report name it as
    unaccounted for instead of reporting a quiet night it cannot see.
    """
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "old", "Old", {"targets": []})
        fake_agent(root, "new", "New", {"targets": []}, extra={
            "contract": "1.1",
            "activity": [sys.executable, "run_agent.py", "--activity"]})
        agents = {a["id"]: a for a in discover.find(root)}

        answer = discover.activity(agents["new"], "2026-09-09T19:00:00+01:00")
        check("the window reaches the agent",
              answer["saw"], {"since": "2026-09-09T19:00:00+01:00"})

        try:
            discover.activity(agents["old"], "2026-09-09T19:00:00+01:00")
        except discover.AgentError as exc:
            check("an agent without the command says so", "activity" in str(exc), True)
        else:
            FAILED.append("an agent without an activity command answered anyway")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_duplicate_id():
    """Two folders claiming one id are two agents, and a click reaches the one clicked.

    This is what a copied repo looks like: `to-dos copy/agents/plan-agent` has
    the same descriptor as the original down to the id, so an id is no longer
    enough to say which one a switch belongs to. Every agent therefore carries a
    `key` — its id while that id is its own, and its id plus where it was found
    when it is not — and the page routes on that.
    """
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "plan-agent", "Night", {"targets": [target()]}, at="to-dos")
        fake_agent(root, "plan-agent", "Night", {"targets": [target()]}, at="to-dos copy")
        fake_agent(root, "lonely", "Lonely", {"targets": [target()]})

        found = discover.find(root)
        keys = sorted(a["key"] for a in found)
        check("an id claimed once is its own key", "lonely" in keys, True)
        check("a shared id is split by where it was found",
              [k for k in keys if k.startswith("plan-agent")],
              ["plan-agent@to-dos", "plan-agent@to-dos copy"])

        copy = routes.find_agent("plan-agent@to-dos copy", root)
        check("a key reaches the folder it names",
              os.path.basename(copy["root"]), "to-dos copy")
        original = routes.find_agent("plan-agent@to-dos", root)
        check("and the other key reaches the other one",
              os.path.basename(original["root"]), "to-dos")

        # The old way of asking still works while it can only mean one thing,
        # and refuses rather than guessing once it cannot.
        check("a plain id still resolves while it is unambiguous",
              routes.find_agent("lonely", root)["id"], "lonely")
        try:
            routes.find_agent("plan-agent", root)
            check("an ambiguous id is refused", True, False)
        except discover.AgentError as exc:
            check("an ambiguous id is refused rather than guessed",
                  "two folders" in str(exc), True)

        # Each card says who its twin is, so a page showing two identical bands
        # explains itself.
        cards = {c["key"]: c for c in (discover.state(a) for a in found)}
        check("a duplicated agent names the other folder",
              cards["plan-agent@to-dos"]["twin"],
              [os.path.join(root, "to-dos copy")])
        check("and an agent on its own has no twin",
              cards["lonely"].get("twin"), None)
    finally:
        shutil.rmtree(root, ignore_errors=True)




def test_reference_agents():
    """Folders with no agent.json, added 19 Sep 2026.

    The walk finds an agent by its descriptor, which two kinds of folder do not
    have — so before this the page could list nothing but the agents already
    spending money overnight. The three things that could go wrong: an entry
    that never appears, one that keeps appearing after the real agent arrives,
    and one that turns out to have a route to a run.
    """
    root = tempfile.mkdtemp()
    refs = os.path.join(root, "references.json")
    try:
        os.makedirs(os.path.join(root, "AGENTS", "ux-agent"))
        os.makedirs(os.path.join(root, "AGENTS", "hand_run"))
        os.makedirs(os.path.join(root, "AGENTS", "grown_agent"))
        with open(refs, "w", encoding="utf-8") as fh:
            json.dump({"references": [
                {"path": "AGENTS/ux-agent", "name": "UX agent",
                 "blurb": "reviews journeys", "cadence": "on demand", "doc": "PLAN.md"},
                {"path": "AGENTS/hand_run", "kind": "built", "name": "Hand run agent",
                 "started_by": "the /do skill", "cadence": "on demand"},
                {"path": "AGENTS/grown_agent", "name": "Grown agent"},
                {"path": "AGENTS/gone", "name": "Gone agent", "kind": "nonsense"},
            ]}, fh)

        # The same list the page is sent, rather than the bare helper: what
        # matters is that a reference agent reaches the cards and stays out of
        # the counts, since nothing about it is armed or running.
        view = routes.state_view(root, refs)
        check("reference agents reach the page beside the real ones",
              [a["name"] for a in view["agents"] if a.get("reference")],
              ["Gone agent", "Grown agent", "Hand run agent", "UX agent"])
        check("and are not counted as agents that are on",
              [c["v"] for c in view["strip"] if c["k"] == "Agents on"], ["0 of 0"])

        found = discover.references(root, refs)
        check("a folder with no descriptor is still drawn",
              [a["name"] for a in found],
              ["Gone agent", "Grown agent", "Hand run agent", "UX agent"])
        by_id = {a["id"]: a for a in found}
        ux = by_id["ux-agent"]
        check("it carries the mark that says there is nothing to run",
              ux["reference"], True)
        check("its cadence, for the sentence on the card", ux["cadence"], "on demand")
        check("and nothing to run", ux.get("actions"), None)
        check("an entry that names no kind is planned, which is what this file "
              "held before kinds existed", ux["kind"], "planned")
        check("a named folder that is not there says so",
              [a["missing"] for a in found if a["name"] == "Gone agent"], [True])

        # The kind added for the to-dos implementing agent. It is not planned:
        # it is written and running, and what it has no answer for is a
        # schedule. A card saying "not built yet" over it would be a plain lie,
        # which is the whole reason the field exists.
        hand = by_id["hand-run-agent"]
        check("an agent that is built but has nothing to schedule says so",
              hand["kind"], "built")
        check("and says what does start it", hand["started_by"], "the /do skill")
        check("and still has no route to a run", hand.get("actions"), None)
        check("a kind this page does not know reads as planned rather than as "
              "an error", by_id["gone-agent"]["kind"], "planned")

        # The one that matters when a plan becomes a scheduled agent. Both
        # halves would otherwise draw it, and the page would show two of the
        # same thing — one of them permanently stuck saying "not built yet".
        fake_agent(os.path.join(root, "AGENTS"), "grown-agent", "Grown agent",
                   {"id": "grown-agent", "name": "Grown agent"}, at="grown_agent")
        after = discover.references(root, refs)
        check("an entry whose folder grew an agent.json drops out of here",
              [a["name"] for a in after], ["Gone agent", "Hand run agent", "UX agent"])
        check("and is found by the walk instead",
              "grown-agent" in [a["id"] for a in discover.find(root)], True)

        # The key this list had while it held only the one kind. A file written
        # before 19 Sep 2026 has to keep drawing, or an upgrade empties the page
        # of everything the walk cannot find.
        legacy = os.path.join(root, "legacy.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            json.dump({"planned": [{"path": "AGENTS/ux-agent", "name": "UX agent"}]}, fh)
        check("the old `planned` key is still read",
              [a["name"] for a in discover.references(root, legacy)], ["UX agent"])

        # A missing or unreadable file is no references at all rather than an
        # error: this is the one file here that is not an agent's own answer,
        # and losing it should cost the extra cards and nothing else.
        check("no file at all is no reference agents",
              discover.references(root, os.path.join(root, "nope.json")), [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def serve(root):
    """A real server on a spare port, looking for agents under `root`."""
    import threading
    from http.server import ThreadingHTTPServer

    handler = type("TestHandler", (routes.ApiHandler,), {"root": root})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def call(url, method="GET", body=None, origin=None):
    """Status, headers and JSON body, whatever the status."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req) as res:
            raw = res.read()
            return res.status, dict(res.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, dict(exc.headers), json.loads(raw) if raw else None


def test_one_agent_route():
    """Another page can read one agent on its own, by key, in any spelling."""
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "a1", "One", {"targets": [target()]})
        fake_agent(root, "twin", "Twin", {}, at="first")
        fake_agent(root, "twin", "Twin", {}, at="second copy")
        srv, base = serve(root)
        try:
            code, _, out = call(base + "/agents/a1")
            check("one agent comes back on its own", (code, out["agent"]["id"]), (200, "a1"))
            check("with the hour to draw its schedule against", "hour" in out, True)
            check("and its targets", [t["id"] for t in out["agent"]["targets"]], ["t1"])

            code, _, out = call(base + "/agents/twin%40second%20copy")
            check("a key with @ and a space is read whole",
                  (code, out["agent"]["root"].endswith("second copy")), (200, True))
            code, _, _ = call(base + "/agents/twin")
            check("an id two folders claim is refused", code, 409)
            code, _, _ = call(base + "/agents/nobody")
            check("an agent that is not there is a 404", code, 404)
        finally:
            srv.shutdown()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cors():
    """Pages on this machine can call in; pages anywhere else cannot."""
    root = tempfile.mkdtemp()
    try:
        fake_agent(root, "a1", "One", {"targets": [target()]})
        srv, base = serve(root)
        try:
            local = "http://localhost:5173"
            _, headers, _ = call(base + "/agents/a1", origin=local)
            check("a local page is told it may read the answer",
                  headers.get("Access-Control-Allow-Origin"), local)
            _, headers, _ = call(base + "/agents/a1", origin="https://example.com")
            check("a remote page is not",
                  headers.get("Access-Control-Allow-Origin"), None)

            code, headers, _ = call(base + "/apply", method="OPTIONS", origin=local)
            check("the browser's question before a POST gets a yes",
                  (code, headers.get("Access-Control-Allow-Headers")), (204, "Content-Type"))
            code, _, _ = call(base + "/apply", method="OPTIONS", origin="https://example.com")
            check("and a no for a remote page", code, 403)

            change = {"agent": "a1", "target": "t1", "changes": {"hours": [2, 3]}}
            code, headers, out = call(base + "/apply", "POST", change, origin="http://127.0.0.1:3000")
            check("a local page can write a schedule",
                  (code, out["saw"]), (200, {"target": "t1", "changes": {"hours": [2, 3]}}))
            check("and read the answer",
                  headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:3000")
            code, _, _ = call(base + "/run", "POST", {"agent": "a1", "action": "run"},
                              origin="https://example.com")
            check("a remote page cannot start anything", code, 403)
            code, _, _ = call(base + "/apply", "POST", change)
            check("a request from outside a browser still works", code, 200)
        finally:
            srv.shutdown()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    test_discovery()
    test_broken_agent()
    test_strip()
    test_window_scope()
    test_boundaries()
    test_routing()
    test_refusal()
    test_activity()
    test_duplicate_id()
    test_reference_agents()
    test_one_agent_route()
    test_cors()
    if FAILED:
        print("%d failed\n" % len(FAILED))
        for f in FAILED:
            print("  " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
