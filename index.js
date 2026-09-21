/* Read an agent's status and write its schedule from any app on this machine.
 *
 * Every call goes to the agents dashboard's own server, which runs the agent's
 * own commands and hands back what the agent said. This file holds no agent
 * logic and no copy of any schedule: it is the four requests the dashboard page
 * already makes, written once so a second app does not write them again.
 */

export const DEFAULT_BASE = 'http://127.0.0.1:8770'

export function createClient({ base = DEFAULT_BASE, fetch: fetchImpl } = {}) {
  const doFetch = fetchImpl || globalThis.fetch.bind(globalThis)
  const root = base.replace(/\/+$/, '')

  async function request(path, body) {
    let res
    try {
      res = await doFetch(root + path, body === undefined
        ? { cache: 'no-store' }
        : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    } catch {
      // A request that never got an answer is almost always a server that is
      // not running, and saying so saves a trip to the network tab.
      throw new Error('The agents dashboard is not answering at ' + root +
        '. Start it with `python3 -m agentsd.server --no-open` in agents-dashboard.')
    }
    const data = await res.json().catch(() => ({}))
    // An agent that refuses a change says why ("07:00 is inside the working
    // day"), and that sentence is the error, not the status code.
    if (!res.ok) throw new Error(data.error || (path + ' answered ' + res.status))
    return data
  }

  const apply = (agent, target, changes) => request('/apply', { agent, target, changes })

  return {
    /* One agent's card and the current hour. */
    getAgent: (key) => request('/agents/' + encodeURIComponent(key)),
    /* Every agent at once, with the strip. Slower: each agent runs its git calls. */
    getAll: () => request('/state.json'),
    /* The hours a target runs at, 0 to 23. An empty list is no hours at all. */
    setHours: (agent, target, hours) => apply(agent, target, { hours }),
    /* A target's switch. */
    setOn: (agent, target, on) => apply(agent, target, { on }),
    /* Any field the agent lists on a target, by that field's own key. */
    setField: (agent, target, key, value) => apply(agent, target, { [key]: value }),
    /* Any change at all, for whatever the helpers above do not cover. */
    apply,
    /* Starts one of the agent's own actions. Answers once it has started. */
    run: (agent, action, target) => request('/run', { agent, action, target }),
  }
}
