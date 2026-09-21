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

await c.getAgent('plan-agent@to-dos copy/agents/plan-agent')
assert.equal(sent.at(-1).url,
  'http://127.0.0.1:8770/agents/plan-agent%40to-dos%20copy%2Fagents%2Fplan-agent')

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

// The schedule arithmetic, the parts where a mistake reads as a true sentence.
const s = await import('./schedule.js')
assert.equal(s.rangeText([22, 23, 0, 1]), '22:00–01:00')
assert.equal(s.rangeText([3, 5, 6]), '03:00 and 05:00–06:00')
assert.equal(s.nextStart([{ hours: [3] }], 4), '03:00 tomorrow')
assert.equal(s.nextStart([{ hours: [3] }], 1), '03:00 today')
const load = s.loadByHour({ hour: 0, agents: [
  { id: 'a', name: 'A', job: { loaded: true }, targets: [{ id: 't', name: 'T', on: true, hours: [2] }, { id: 'u', name: 'U', on: false, hours: [2] }] },
  { id: 'b', name: 'B', job: { loaded: false }, targets: [{ id: 'v', name: 'V', on: true, hours: [2] }] },
] })
assert.deepEqual(load.who[2], ['T'])
assert.equal(s.autonomy({ id: 'a', name: 'A', targets: [{ id: 't', name: 'T', on: false, hours: [2] }] }, 0).head, 'Nothing armed')
console.log('schedule checks passed')
