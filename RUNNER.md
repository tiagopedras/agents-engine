# The runner, version 0.1

The part of the engine that works through a queue unattended. Planned and built
on 21 Sep 2026. The code is `python/agents_engine/runner/`, the single wake is
`python/agents_engine/wake.py`, and `python/test_runner.py` checks both against
a fake agent and a fake `claude`. The UX agent is the first agent on it.

## Why it exists

Two agents on this machine work a queue on their own overnight: the to-dos
planning agent and `improve_agent`. Each wrote its own loop. Both have an hourly
wake that checks a schedule, a lock that records which process holds it, a pass
that picks what to work on and skips what has not changed, one `claude -p` per
item with a budget and a time limit, a run record the dashboard reads, and a
`dashboard.py` of about 550 lines answering the dashboard's four commands. The
planning agent's version alone is close to 6,000 lines, and most of what is hard
about it (the stale lock, the usage limit that looked like an ordinary failure,
the second run of the day that hid the first) had to be learnt there and then
copied by hand into `improve_agent`.

The UX agent is the third. Rather than a third copy, the loop moves here, and an
agent built on it writes only what is its own: which queue, which items, what to
ask Claude, and where the answer goes.

It sits in `agents_engine` because that package already answers the dashboard's
questions about agents. The runner is the other side of the same contract: the
engine already knows how to ask an agent what state it is in, and this lets the
engine be the agent's answer as well.

## Three parts, three owners

| Part | Owner | Holds |
| --- | --- | --- |
| The queue | `PACKAGES/work_streams` | what an item is, its states, who may write it |
| When things run, and whether two overlap | `agents-dashboard` | hours, switches, and the view of what collides |
| Working through a queue | this runner | everything below |

The runner never decides whether two agents may run at once. Each agent has its
own lock and runs at the hours set for it. If two are set for the same hour they
both run, and the dashboard already shows that collision so it can be moved.

## What the runner does

1. **The wake.** Asked every hour. Reads the agent's own schedule and stops at
   once if no target names this hour or its switch is off.
2. **The lock.** One per target. Records the process ID. A lock whose process is
   dead is cleared whatever its age. A live one is left alone however old it
   looks, because a laptop shut mid-run suspends the holder rather than killing
   it. Age is only the fallback for a lock that names no process.
3. **Reading the queue.** Through `work_streams`: items that are `ready`, owned by
   this agent, and not marked `needs_you`.
4. **Skipping what has not changed.** A ledger per target holds a fingerprint of
   each item as it was when last run. An item whose fingerprint matches, and
   whose last result has not been sent back, is passed over.
5. **Running one item.** One `claude -p` at a time, with the agent definition,
   prompt, tools, folders, model, per-item budget and time limit the agent
   names. Captures the session, the cost and the text.
6. **Stopping.** Before each item: the night's budget, the item cap, the end of
   the scheduled hours. After each item: a usage limit, which ends the run and
   records the reset time. If the first two items fail for the same reason,
   the run stops rather than failing every item the same way.
7. **Writing back.** Moves each item `ready` to `doing` before the run and to
   `review` (owner `me`) after, through the stream's own writer, never by
   opening the file. An item the agent says it could not finish without a person
   goes back with `needs_you` and a line of `feedback`.
8. **Failures.** A failed item stays `ready` and is tried again next run. After
   three failures in a row it moves to `blocked`, owner `me`, `needs_you`, with
   the error as its `feedback`, so it stops costing a night and appears on the
   board.
9. **The daily log.** Below.
10. **The notification.** One line at the end of a run that did something or
    failed at something. Never one per item.
11. **Manual modes.** A dry run that says what would run and spends nothing, at
    any hour. One named item, run now, outside the schedule.
12. **Clean-up.** Daily logs older than 30 days are deleted. Queue items never
    are: what happened to one is on the item itself.
13. **The dashboard's commands.** `state`, `apply`, `run` and `activity` are
    answered by the runner for any agent built on it, from the schedule, ledger
    and run records above. An agent adds cards, stats or fields of its own only
    if it wants to.

## What an agent provides

A folder with an `agent.json` (the dashboard contract), a `stream.json` (the
queue), a `hooks.py`, and a `run.py` of a few lines that puts this package on
the path and calls `runner.main(hooks, folder)`. Every command in `agent.json`
points at `run.py`; `AGENTS/ux_agent/` is the example to copy.

The queue must be a folder of documents. Its `container.path` may hold
`<target>`, which the runner fills with the target's id, so one manifest serves
one folder per target.

`hooks.py` holds `ID`, `NAME` and `BLURB`, optionally `HOURS_PREFERRED` and
`FIELDS` (extra settings, in the dashboard's field shape plus a `default`), and
these functions:

| Hook | Answers |
| --- | --- |
| `targets()` | what the switches and schedules belong to: one repo, one list, one client |
| `stream(target)` | where that target's queue is |
| `eligible(item, target)` | `None`, or the reason this item is not run. The reason goes into the log as given |
| `order(items, target)` | optional, the order to work in. Default is the queue's own |
| `prompt(item, target)` | what Claude is asked |
| `options(item, target)` | agent definition, tools, extra folders, model, per-item budget, time limit |
| `land(item, result, target)` | writes the output where it belongs and returns what to log: a ref, a one-line summary, a detail line, and whether it needs a person |
| `explain(error, kind)` | optional, `(what happened, what fixes it)` for an error this agent knows about |
| `problems(target)` | optional, lines the dashboard shows on the target's row |

Settings kept per target, edited only through `apply`: `on`, `hours`, `budget`
(the night), `max_items`, and anything the agent declares in `fields`.

## The single wake

One launchd job, `com.tiagopedras.agents-wake`, wakes every hour and runs
`python3 -m agents_engine.wake`. That finds every agent the way the dashboard
does and runs each one's `wake` command, each in its own process, without
waiting for the others. The agent decides whether this hour is one of its own.

`wake` is a fifth, optional command in `agent.json`, arriving with contract
version 1.7:

```json
"wake": ["python3", "run.py", "--wake"]
```

An agent on the runner points it at its `run.py`. An agent not on it yet points it
at its own entry point, which for the planning agent and `improve_agent` is the
`run.sh` their own plists run today. Once an agent's `agent.json` has `wake`, its
own plist is unloaded, and the dashboard stops showing a `job` for it. An agent
without `wake` is not woken by this, which is how the two old plists keep working
while agents move over one at a time.

## The daily log

One readable file per target per day, `state/<target>/runs/YYYY-MM-DD.md` in
the agent's folder, plus the `.json` beside it holding the same facts for
`activity`. A second run on the same day adds to the file rather than starting
another, so the day is always read in one place.

It answers three questions in this order: what ran, what did not, and what
failed. Wakes where nothing was due are one line at the bottom, not one line per
hour.

```markdown
# UX agent · tiago · Sun 21 Sep 2026

2 ran · 1 not run · 1 failed · $3.40 of $6.00

## Ran
- **Plans view on mobile** · review written · $1.60 · 02:04
  reviews/2026-09-21-plans-mobile/review.md
  Provisional: 3 questions for you at the top.
- **Desk yoga reminder toast** · review written · $1.80 · 02:11
  reviews/2026-09-21-desk-yoga-toast-2/review.md

## Not run
- **Agents dashboard, first visit** · no angle given. Add one to the queue item.

## Failed
- **Bench onboarding** · 02:15 · the page did not load (localhost:8765 refused).
  Start the board and it runs next time. Failed 1 of 3 before it is set aside.

## Wakes
02:00 ran. 00:00–01:00 and 03:00–23:00: nothing scheduled.
```

Every line in **Not run** and **Failed** carries a reason in plain words and,
where one exists, what fixes it. The runner has built-in readings for the common
failures: an agent definition that is missing, a time limit, a per-item budget
hit, a usage limit with its reset time, `claude` not found, and output the agent
could not land. `explain()` adds the agent's own. An error neither recognises is
quoted as its first line, which is still better than a count.

A run that stopped early says why under the counts line. A day with failures
turns the target's card on the dashboard to the `bad` tone until the next run
succeeds.

`runner.log` beside it stays as the raw, append-only trace for when something
needs debugging. Nobody is expected to read it in the morning.

## What stays out

- **Which agents may overlap.** The dashboard's call.
- **The queue's shape.** `work_streams`.
- **Anything that has to stop and ask.** The implementing agent runs only from a
  session through `/do`, and never gets a runner.
- **What any agent's output means.** The runner logs what `land` returns and
  never reads a plan, a branch or a review.

## Installing the wake

```bash
ln -s ~/Code/PACKAGES/agents_engine/launchd/com.tiagopedras.agents-wake.plist \
      ~/Library/LaunchAgents/com.tiagopedras.agents-wake.plist
launchctl load ~/Library/LaunchAgents/com.tiagopedras.agents-wake.plist
```

`python3 -m agents_engine.wake --list` (from `python/`) says which agents it
wakes. What each one did is in its own daily log; the wake's own line per agent
is in `~/Library/Logs/agents-wake.log`.

## Order of work

1. ~~This file agreed.~~
2. ~~The runner and the single wake, built here with tests.~~
3. ~~The UX agent as the first agent on it.~~
4. `improve_agent` moved over.
5. The planning agent moved over last, as the largest, keeping its own briefs,
   brief-writing and reports as hooks and extra steps around the runner.
