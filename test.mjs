/* Checks the requests this client sends, against a fake fetch. The server side
 * is tested in agents-dashboard/test_agentsd.py; what is worth checking here is
 * that each helper sends what the server expects.
 *
 *     node test.mjs
 */

import assert from 'node:assert/strict'
import { createClient } from './index.js'

const sent = []
function fake(status, body) {
  return async (url, init = {}) => {
    sent.push({ url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined })
    return { ok: status < 400, status, json: async () => body }
  }
}

let c = createClient({ base: 'http://127.0.0.1:8770/', fetch: fake(200, { ok: true }) })

await c.getAgent('planning-agent@to-dos copy/agents/planning_agent')
assert.equal(sent.at(-1).url,
  'http://127.0.0.1:8770/agents/planning-agent%40to-dos%20copy%2Fagents%2Fplanning_agent')

await c.setHours('improve-agent', 'to-dos', [2, 3])
assert.deepEqual(sent.at(-1), { url: 'http://127.0.0.1:8770/apply', method: 'POST',
  body: { agent: 'improve-agent', target: 'to-dos', changes: { hours: [2, 3] } } })

await c.setOn('improve-agent', 'to-dos', false)
assert.deepEqual(sent.at(-1).body.changes, { on: false })

await c.setField('improve-agent', 'to-dos', 'budget', 4)
assert.deepEqual(sent.at(-1).body.changes, { budget: 4 })

await c.run('improve-agent', 'dry')
assert.deepEqual(sent.at(-1).body, { agent: 'improve-agent', action: 'dry' })

// The agent's own reason is the error.
c = createClient({ fetch: fake(400, { error: '07:00 is inside the working day' }) })
await assert.rejects(c.setHours('a', 't', [7]), /07:00 is inside the working day/)

// A server that is not running says so.
c = createClient({ fetch: async () => { throw new TypeError('fetch failed') } })
await assert.rejects(c.getAll(), /not answering/)

console.log('all checks passed')
