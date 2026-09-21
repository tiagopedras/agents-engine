"""One `claude -p` for one item, and what its failures mean in plain words.

The error readings here are the ones the Plan agent learnt the hard
way. A usage limit whose wording named neither "usage" nor "at" was once read
as an ordinary failure, and the batch went on to fail the same way twenty-four
more times in a minute. So a limit is matched loosely, and a stray match costs
an early night rather than a wasted one.

`AGENTS_RUNNER_CLAUDE` replaces the binary, which is how the tests run without
spending anything.
"""

import json
import os
import re
import subprocess

LIMIT_RE = re.compile(
    r"((usage|rate|session|weekly|daily)\s+limit|limit reached"
    r"|resets?\s+(?:at\s+)?\d{1,2}:\d{2})", re.I)
RESET_RE = re.compile(r"resets? (?:at )?([0-9]{1,2}:[0-9]{2}\s*(?:am|pm)?)", re.I)
AGENT_RE = re.compile(r"--agent '([^']+)' not found|agent '?([\w.-]+)'? (?:was )?not found", re.I)
BUDGET_RE = re.compile(r"budget", re.I)

DEFAULTS = {"agent": None, "tools": ["Read", "Grep", "Glob"], "disallowed": [], "dirs": [],
            "model": None, "permission_mode": None, "budget": 2.0, "timeout": 15 * 60, "cwd": None}


class Result(object):
    def __init__(self, text=None, session=None, cost=0.0, error=None, kind=None):
        self.text, self.session, self.cost, self.error, self.kind = text, session, cost or 0.0, error, kind

    def as_dict(self):
        return {"text": self.text, "session": self.session, "cost": self.cost}


def command(prompt, opts):
    cmd = [os.environ.get("AGENTS_RUNNER_CLAUDE", "claude"), "-p", prompt,
           "--output-format", "json", "--max-budget-usd", "%.2f" % float(opts["budget"])]
    if opts.get("agent"):
        cmd += ["--agent", opts["agent"]]
    if opts.get("model"):
        cmd += ["--model", opts["model"]]
    if opts.get("permission_mode"):
        cmd += ["--permission-mode", opts["permission_mode"]]
    if opts.get("tools"):
        cmd += ["--allowedTools"] + list(opts["tools"])
    if opts.get("disallowed"):
        cmd += ["--disallowedTools"] + list(opts["disallowed"])
    for d in opts.get("dirs") or []:
        cmd += ["--add-dir", os.path.expanduser(d)]
    return cmd


def classify(err):
    if not err:
        return None
    if LIMIT_RE.search(err):
        return "limit"
    if AGENT_RE.search(err):
        return "missing_agent"
    if BUDGET_RE.search(err):
        return "budget"
    return "other"


def run(prompt, opts):
    cmd = command(prompt, opts)
    try:
        proc = subprocess.run(cmd, cwd=opts.get("cwd"), capture_output=True, text=True,
                              timeout=opts["timeout"])
    except subprocess.TimeoutExpired:
        return Result(error="timed out after %d minutes" % (opts["timeout"] // 60), kind="timeout")
    except OSError as exc:
        return Result(error="could not start claude: %s" % exc, kind="claude_missing")

    raw = (proc.stdout or "").strip()
    try:
        res = json.loads(raw)
    except ValueError:
        err = (proc.stderr or raw or "no output").strip()[:600]
        return Result(error=err, kind=classify(err))
    text = res.get("result") or res.get("text") or ""
    session = res.get("session_id") or res.get("sessionId")
    cost = res.get("total_cost_usd") or res.get("cost_usd") or 0.0
    subtype = res.get("subtype") or ""
    if res.get("is_error") or subtype.startswith("error") or not text.strip():
        err = (res.get("error") or text or subtype or "empty result").strip()[:600]
        if "budget" in subtype:
            return Result(session=session, cost=cost, error=err, kind="budget")
        return Result(session=session, cost=cost, error=err, kind=classify(err))
    return Result(text=text, session=session, cost=cost)


def reset_time(err):
    m = RESET_RE.search(err or "")
    return m.group(1) if m else None


def explain(result, opts):
    """(what happened, what fixes it), both in plain words."""
    k, err = result.kind, result.error or ""
    first = err.strip().splitlines()[0][:200] if err.strip() else "no message"
    if k == "limit":
        when = reset_time(err)
        return ("hit the usage limit%s" % (", resets %s" % when if when else ""),
                "Nothing to fix. The rest wait for the next scheduled hour.")
    if k == "missing_agent":
        m = AGENT_RE.search(err)
        name = (m.group(1) or m.group(2)) if m else opts.get("agent")
        return ("the agent definition %r is missing" % name,
                "Write .claude/agents/%s.md, or check its symlink." % name)
    if k == "timeout":
        return ("took longer than %d minutes and was stopped" % (opts["timeout"] // 60),
                "Raise the time limit or make the item smaller.")
    if k == "budget":
        return ("used its whole $%.2f before finishing" % float(opts["budget"]),
                "Raise the per-item budget or make the item smaller.")
    if k == "claude_missing":
        return ("`claude` could not be started (%s)" % first,
                "Check that its folder is on the PATH in the wake's launchd file.")
    if k == "land":
        return ("the answer could not be saved: %s" % first,
                "Check the agent's land() hook against what Claude returned.")
    return (first, "")
