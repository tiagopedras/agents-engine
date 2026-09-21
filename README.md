# agents_engine

Everything needed to monitor the scheduled agents on this machine and change
their schedules, without the page. The agents dashboard is one app built on it.
Anything else that needs to show an agent's status, draw what runs tonight, or
move a schedule builds on the same engine rather than starting again.

It comes in three parts, and an app takes the ones it needs:

| Part | Language | What it does |
| --- | --- | --- |
| `python/agents_engine/discover.py` | Python | Finds every agent (a folder under `~/Code` with an `agent.json`) and runs its own commands: `state`, `apply`, `run`, `activity` |
| `python/agents_engine/routes.py` | Python | The HTTP routes over that: `/state.json`, `/agents/<key>`, `/apply`, `/run`, and the rule on which pages may call in |
| `python/agents_engine/runner/` + `wake.py` | Python | The runner: works through an agent's queue unattended, and one hourly wake for every agent. An agent writes only its hooks. `RUNNER.md` is the guide |
| `index.js` + `schedule.js` | JavaScript, with types | A client for those routes, and the arithmetic over what comes back: what runs at each hour, what collides, when the next run is, how a run reads in words |

The agent's own config stays the only place its schedule is kept. Nothing here
opens an agent's files: it runs the agent's own commands and passes the answer
on, so a second app can never become a second writer for a schedule.
`CONTRACT.md` in `agents-dashboard` is the shape of what an agent prints and
accepts.

## Two ways to build an app on it

A browser page cannot run an agent's commands, so every app has a server
somewhere. The choice is whose.

1. **Use the dashboard's server.** Your page calls `http://127.0.0.1:8770` with
   the JavaScript client. Nothing to run of your own, but the dashboard server
   has to be running (`python3 -m agentsd.server --no-open` in
   `agents-dashboard`).
2. **Mount the routes in your own Python server.** Your app answers the same
   four routes itself and needs nothing else running. The to-dos board's
   `kanban/server.py` is the kind of server this fits.

Either way, pages are only answered when served from `localhost` or
`127.0.0.1`, on any port. Every other website is refused with a 403, because a
tab on any site can send a request to loopback and these routes can start an
agent overnight. A script run from a terminal sends no origin and is let
through.

## The Python side

Put `python/` on the path, the way `agents-dashboard/agentsd/__init__.py` does,
then either serve the routes as they are:

```python
from agents_engine import routes

routes.serve(8771).serve_forever()        # loopback only, always
```

or subclass the handler to serve your own page beside them:

```python
class Handler(routes.ApiHandler):
    refs = "/path/to/your/references.json"   # optional: agents with no agent.json yet

    def do_GET(self):
        if self.path == "/":
            return self._send(200, MY_PAGE, "text/html; charset=utf-8")
        return self.api_get(self.path.split("?")[0])

routes.serve(8771, Handler).serve_forever()
```

Or skip HTTP entirely and ask the agents directly, which is what the
`agents-report` skill does:

```python
from agents_engine import discover

for agent in discover.find():
    card = discover.state(agent)                     # what the dashboard draws
discover.apply(agent, "PACKAGES/tenon", {"hours": [2, 3]})
```

`routes.state_view()` and `routes.agent_view(key)` return the same JSON the
routes send, for a server that wants to shape its own.

## The JavaScript side

It is plain JavaScript with types beside it, so there is no build step. Add it
by path, relative to your app's own folder:

```json
"dependencies": {
  "@tiagopedras/agents-engine": "file:../PACKAGES/agents_engine"
}
```

Moving this folder breaks that path and the symlink npm made from it, the same
way it does for `ai_chat_engine`.

### Reading and writing

```js
import { createClient } from '@tiagopedras/agents-engine'

const agents = createClient()   // or createClient({ base: 'http://127.0.0.1:8771' })

const { hour, agent } = await agents.getAgent('improve-agent')
await agents.setHours('improve-agent', 'PACKAGES/tenon', [2, 3, 4])
await agents.setOn('improve-agent', 'PACKAGES/tenon', false)
await agents.setField('improve-agent', 'PACKAGES/tenon', 'budget', 4)
```

| Call | Does |
| --- | --- |
| `getAgent(key)` | one agent's card and the current hour |
| `getAll()` | every agent at once, plus the strip. Slower, since every agent runs its git calls |
| `setHours(agent, target, hours)` | the hours a target runs at, `0` to `23`. `[]` is no hours at all |
| `setOn(agent, target, on)` | a target's switch |
| `setField(agent, target, key, value)` | any field the agent lists under a target's `fields`, by that field's `key` |
| `apply(agent, target, changes)` | any change, for whatever the three above do not cover |
| `run(agent, action, target?)` | starts one of the agent's `actions`, such as `run` or `dry`. Answers once it has started |

Every call throws an `Error` when it fails. When an agent refuses a change, the
message is the agent's own reason, such as "07:00 is inside the working day",
so it can be shown as it is. When the server is not answering, the message
says so.

### The arithmetic

```js
import { loadByHour, rangeText, autonomy, runLine } from '@tiagopedras/agents-engine/schedule.js'

const state = await agents.getAll()
loadByHour(state).who[3]            // the targets armed at 03:00; two or more is a collision
rangeText([22, 23, 0, 1])           // "22:00–01:00"
autonomy(agent, hour)               // { head: "Next run", text: "03:00 tomorrow", ... }
runLine(target.last_run)            // { text: "2026-09-21 03:05 · $1.20 · 2 of 3 built" }
```

| Function | Answers |
| --- | --- |
| `loadByHour(state)` | how many armed targets fall in each hour, and which. Skips anything switched off or whose scheduler is not loaded |
| `rangeText(hours)`, `hourRanges(hours)` | a schedule as stretches, wrapping midnight |
| `nextStart(targets, hour)` | the next hour any of them could start, with "today" or "tomorrow" |
| `autonomy(agent, hour)` | one line on whether the agent does anything unasked: next run, nothing armed, held back, on demand, or not built |
| `jobLine(agent)` | whether the hourly wake is loaded |
| `runLine(run)`, `builtLastRun(run)`, `builtLastNight(run)` | the last run in words, and what it built |
| `byName`, `allTargets`, `keyOf`, `rowKey` | ordering and addressing |
| `STATUS`, `statusOf`, `cardLabel`, `estimateText` | the six work states and how an entry's cost estimate reads |

## What an agent's card holds

`index.d.ts` has the shape typed, and the dashboard's own page reads its types
from there too. The parts a status view usually needs:

- `agent.summary` and `agent.tone`, the one line the agent writes about itself
  and whether it is fine.
- `agent.running`, true while a run is going.
- `agent.targets`, one per thing the agent works on, each with `on`, `hours`,
  `counts` and `last_run`. A target's `id` is what the write calls take. For the
  improvements agent it is the repo's path under `~/Code`, such as
  `PACKAGES/tenon`.
- `agent.broken`, set instead of everything else when the agent could not
  answer. Draw it rather than hiding the agent.

Whether a schedule can be edited is the agent's call. Leave `hours` alone on a
target with `hours_editable: false`, and `on` alone where `switchable` is false.
Both are left out when they are true, which is the usual case.

## Keys

An agent is addressed by its id, `improve-agent` or `planning-agent`, which is
the `key` on its card. When two folders claim the same id (a copied repo brings
the copy's `agent.json` with it) the key becomes `id@folder`, and asking for
the bare id is refused with a 409 rather than guessed at. Use `agent.key` from
a card you have already read and this never comes up.

## Checks

```
npm test
```

That runs `test.mjs` (the client's requests and the arithmetic) and
`python/test_engine.py` (discovery and the routes, against fake agents rather
than the real ones, so nothing is ever spent).
