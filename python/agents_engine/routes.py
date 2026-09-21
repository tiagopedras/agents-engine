"""The HTTP side of the engine: what an app is told about its agents, and the
routes that carry it.

Any Python server can mount `ApiHandler` (or subclass it and add its own pages,
which is what the agents dashboard does) and answer:

    GET  /state.json      every agent, plus the strip across the top
    GET  /agents/<key>    one agent on its own
    POST /apply           a change to one target, passed to the agent unedited
    POST /run             one of the agent's actions, started detached

Everything here is loopback-only by design. Pages on localhost and 127.0.0.1 may
call in from any port; every other origin is refused.
"""

import datetime as dt
import json
import re
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from . import discover

# --------------------------------------------------------------------------
# what an app is told


def state_view(root=None, refs=None):
    """Every agent's card, gathered in parallel, plus the strip across the top.

    In parallel because each `state` call shells out to git in every repo that
    agent serves, and doing three of those in sequence is three times a wait
    that is already the slowest thing on the page.
    """
    agents = discover.find(root)
    if agents:
        with ThreadPoolExecutor(max_workers=min(8, len(agents))) as pool:
            cards = list(pool.map(discover.state, agents))
    else:
        cards = []
    # Last, and after the strip is counted rather than before it. A reference
    # agent has nothing armed and nothing running, so counting it into "5 of 9
    # on" would make the page read worse the more work is queued up ahead of it.
    planned = discover.references(root, refs)
    now = dt.datetime.now().astimezone()
    return {"now": now.isoformat(), "hour": now.hour,
            "agents": cards + planned, "strip": strip(cards),
            "boundaries": boundaries(account_window(cards))}


def account_window(cards):
    """The one agent's window that stands for the whole account, or nothing.

    The usage window is a property of the account rather than of any one agent,
    so one answer stands for all of them — but only from an agent that reports
    the window and nothing else. The Plan agent's copy of the arithmetic
    short-circuits on its own hours before it looks at a window at all, so
    during the day it says STOP about its schedule while meaning nothing about
    the account. An agent that does that marks its answer `scope: "self"`, and
    this prefers anything that has not.
    """
    windows = [c["window"] for c in cards if c.get("window")]
    return next((w for w in windows if w.get("scope") != "self"), None) \
        or (windows[0] if windows else None)


def boundaries(window):
    """Where the five-hour windows opened, for the marks down the hour track.

    One list on the page rather than one per panel, for the same reason the
    strip quotes one window: where a window opened is a fact about the account,
    and two panels disagreeing about it would be two facts.

    An entry with no `at` is dropped rather than drawn at midnight, which is
    where a mark with no time would land and where it would be believed. The
    field arrived with contract 1.4 and every agent on this machine predates it,
    so a window with no boundaries on it is the ordinary case and an empty list
    is a track with no marks, exactly as before.
    """
    return [b for b in ((window or {}).get("boundaries") or [])
            if isinstance(b, dict) and b.get("at")]


def strip(cards):
    """The five numbers across the top, gathered across every agent.

    Cross-agent on purpose. The question this page is opened to answer is what
    is running tonight, and an answer split into one row per agent would make
    the reader add up.
    """
    targets = [t for c in cards for t in c.get("targets", [])]
    on = [t for t in targets if t.get("on")]
    armed = [c for c in cards if (c.get("job") or {}).get("loaded")]
    broken = [c for c in cards if c.get("broken")]

    window = account_window(cards)

    out = [
        {"k": "Agents on", "v": "%d of %d" % (len(on), len(targets)),
         "w": ", ".join(t["name"] for t in on) if on else "nothing is switched on"},
        {"k": "Schedulers", "v": "%d of %d" % (len(armed), len(cards)),
         "w": "launchd has the hourly wake loaded" if len(armed) == len(cards) and cards
              else "one or more is not loaded — see the agent's own band",
         "cls": "ok" if cards and len(armed) == len(cards) else "bad"},
    ]
    if window:
        out.append({"k": "Usage window", "v": window["action"].upper(), "w": window["why"],
                    "cls": {"ride": "ok", "open": "ok", "stop": "stop"}.get(window["action"], "")})
    if broken:
        out.append({"k": "Not answering", "v": str(len(broken)),
                    "w": ", ".join(c["name"] for c in broken), "cls": "bad"})

    # Whatever each agent thinks is worth a number of its own, after the ones
    # this page works out for itself.
    for card in cards:
        for stat in card.get("stats") or []:
            out.append(dict(stat))
    return out


def agent_view(agent_key, root=None):
    """One agent's card on its own, for a page somewhere else that shows one.

    Only that agent's `state` is run, so it costs one agent's git calls rather
    than every agent's. The hour comes with it because a schedule is drawn
    against the current hour and the other page should not need its own clock
    to agree with this one. None when no agent answers to the key.
    """
    agent = find_agent(agent_key, root)
    if not agent:
        return None
    now = dt.datetime.now().astimezone()
    return {"now": now.isoformat(), "hour": now.hour, "agent": discover.state(agent)}


def find_agent(agent_key, root=None):
    """The one agent a click names, or nothing, or a refusal.

    A key is an agent's id while that id is its own, and its id plus where it
    was found once a second folder claims the same one — a copied repo brings a
    whole second agent, descriptor and id included. Matching on the id alone
    meant the first one the walk turned up answered for both, so switching off
    the copy switched on the original.

    A bare id is still accepted, because it is what a key is in the ordinary
    case and what anything written against the old shape sends. It is refused
    rather than guessed at when two folders answer to it.
    """
    agents = discover.find(root)
    for agent in agents:
        if agent.get("key") == agent_key:
            return agent
    claimants = [a for a in agents if a["id"] == agent_key]
    if len(claimants) > 1:
        raise discover.AgentError(
            "two folders claim the id %r — %s. Say which one by its key."
            % (agent_key, " and ".join(a["root"] for a in claimants)))
    return claimants[0] if claimants else None



# --------------------------------------------------------------------------
# serving it


# Pages allowed to call this server from another port: anything served on this
# machine's loopback. Every other origin is refused, because a browser tab on
# any website can send a request to 127.0.0.1, and this server can start an
# agent that writes code overnight.
LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")


def origin_allowed(origin):
    """No Origin header is a request from outside a browser, which is allowed."""
    return not origin or bool(LOCAL_ORIGIN.match(origin))



class ApiHandler(BaseHTTPRequestHandler):
    """The four routes, with nothing else. Subclass it to serve a page as well:
    override `do_GET`, answer your own routes, and hand the rest to
    `self.api_get(route)`."""

    # Where agents are looked for. None is ~/Code; the tests point it at a
    # folder of fake agents.
    root = None
    # The app's own references.json, if it keeps one. None draws no reference
    # agents at all.
    refs = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        # The browser's question before a JSON POST from another port. A yes
        # carries the headers; a no is a bare 403 and the browser stops there.
        if not origin_allowed(self.headers.get("Origin")):
            return self._send(403, {"error": "origin not allowed"})
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError):
            return {}

    def do_GET(self):
        self.api_get(self.path.split("?")[0])

    def api_get(self, route):
        if route == "/state.json":
            return self._send(200, state_view(self.root, self.refs))
        if route.startswith("/agents/"):
            # A key can hold "@", spaces and slashes, so everything after the
            # prefix is the key, decoded once.
            key = unquote(route[len("/agents/"):])
            try:
                view = agent_view(key, self.root)
            except discover.AgentError as exc:
                return self._send(409, {"error": str(exc)})
            if not view:
                return self._send(404, {"error": "no agent %r" % key})
            return self._send(200, view)
        return self._send(404, {"error": "no route %s" % route})

    def do_POST(self):
        route = self.path.split("?")[0]
        # Checked before anything is read. A form on any website can post here
        # without the browser asking first, so the CORS headers alone would
        # stop it reading the answer and not stop the agent starting.
        if not origin_allowed(self.headers.get("Origin")):
            return self._send(403, {"error": "origin not allowed"})
        body = self._body()
        try:
            agent = find_agent(body.get("agent", ""), self.root)
        except discover.AgentError as exc:
            return self._send(409, {"error": str(exc)})
        if not agent:
            return self._send(404, {"error": "no agent %r" % body.get("agent")})

        try:
            if route == "/apply":
                out = discover.apply(agent, body.get("target"), body.get("changes") or {})
            elif route == "/run":
                out = discover.start(agent, body.get("action"), body.get("target"))
            else:
                return self._send(404, {"error": "no route %s" % route})
        except discover.AgentError as exc:
            return self._send(502, {"error": str(exc)})

        if out.get("ok") is False:
            return self._send(400, {"error": out.get("error") or "refused"})
        return self._send(200, out)


def serve(port, handler=ApiHandler):
    """A server on loopback only, never a network interface: it can start an
    agent that writes code at 4am."""
    return ThreadingHTTPServer(("127.0.0.1", port), handler)
