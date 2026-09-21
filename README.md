# agents_client

How another app on this machine shows a scheduled agent's status and changes its
schedule. It makes the same requests the agents dashboard page makes, so a
second app can draw its own version of a card and write back to the same agent
without knowing anything about how that agent keeps its config.

It is a client and nothing more. It talks to the agents dashboard's server,
which runs each agent's own commands and hands back what the agent said. The
server is the only thing that reaches an agent, and the agent's own config stays
the only place its schedule is kept, so a second app can never become a second
writer for a schedule.

## Before it works

The dashboard server has to be running. It is running whenever the dashboard is
open; to run it without opening a browser:

```
cd ~/Code/agents-dashboard && python3 -m agentsd.server --no-open
```

It answers on `http://127.0.0.1:8770`. The routes this client calls arrived on
the `agent-api` branch of `agents-dashboard` on 21 Sep 2026, so that branch has
to be merged and the server restarted before any of this answers.

Your app has to be served from `localhost` or `127.0.0.1`, on any port. A Vite
dev server, the to-dos board and anything opened from a local Python server all
qualify. A page served from anywhere else is refused with a 403, because a tab
on any website can send a request to loopback and this server can start an
agent overnight. A script run from a terminal sends no origin at all and is let
through.

## Adding it to an app

It is not published or on GitHub yet, so it is loaded by path:

```json
"dependencies": {
  "@tiagopedras/agents-client": "file:../PACKAGES/agents_client"
}
```

The path is relative to the app's own folder, so adjust the `../` to match, and
run `npm install`. Moving this folder breaks that path and the symlink npm made
from it, the same way it does for `ai_chat_engine`. It is plain JavaScript with
types beside it, so there is no build step here and nothing to rebuild after an
edit.

## Using it

```js
import { createClient } from '@tiagopedras/agents-client'

const agents = createClient()   // or createClient({ base: 'http://127.0.0.1:8779' })

// Read one agent. `hour` is the server's current hour, to draw a schedule against.
const { hour, agent } = await agents.getAgent('improve-agent')
for (const t of agent.targets ?? []) {
  console.log(t.name, t.on ? 'on' : 'off', t.hours)
}

// Write back.
await agents.setHours('improve-agent', 'PACKAGES/tenon', [2, 3, 4])
await agents.setOn('improve-agent', 'PACKAGES/tenon', false)
await agents.setField('improve-agent', 'PACKAGES/tenon', 'budget', 4)
```

| Call | Does |
| --- | --- |
| `getAgent(key)` | one agent's card and the current hour |
| `getAll()` | every agent at once, plus the strip across the top of the dashboard. Slower, since every agent runs its git calls |
| `setHours(agent, target, hours)` | the hours a target runs at, `0` to `23`. `[]` is no hours at all |
| `setOn(agent, target, on)` | a target's switch |
| `setField(agent, target, key, value)` | any field the agent lists under a target's `fields`, by that field's `key` |
| `apply(agent, target, changes)` | any change, for whatever the three above do not cover |
| `run(agent, action, target?)` | starts one of the agent's `actions`, such as `run` or `dry`. It answers once the run has started, not when it finishes |

Every call returns a promise and throws an `Error` when it fails. When an agent
refuses a change, the message is the agent's own reason, such as "07:00 is
inside the working day", so it can be shown to the person as it is. When the
server is not running, the message says so.

## What an agent's card holds

`index.d.ts` has the shape typed. The parts a status view usually needs:

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
Both are left out when they are true, which is the usual case. The full contract, including every optional key, is `CONTRACT.md` in
`agents-dashboard`, under `state`.

## Keys

An agent is addressed by its id, `improve-agent` or `planning-agent`, which is
the `key` on its card. When two folders claim the same id (a copied repo brings
the copy's `agent.json` with it) the key becomes `id@folder`, and asking for
the bare id is refused with a 409 rather than guessed at. Use `agent.key` from
a card you have already read and this never comes up. The client encodes the
key for you.

## Without this package

Anything that can make an HTTP request can do the same, a Python script
included. The routes are listed in the `agents-dashboard` README, under
"Reading and writing an agent from another app":

```
curl -s http://127.0.0.1:8770/agents/improve-agent
curl -s -X POST http://127.0.0.1:8770/apply \
  -H 'Content-Type: application/json' \
  -d '{"agent": "improve-agent", "target": "PACKAGES/tenon", "changes": {"hours": [2, 3]}}'
```

## Checks

```
node test.mjs
```

It checks what each call sends, against a fake server. The server side is
checked in `agents-dashboard/test_agentsd.py`.
