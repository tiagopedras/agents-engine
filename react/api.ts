/* Where the four routes are answered. The agents dashboard serves them at its
 * root; the to-dos board mounts them under /agents-api so they cannot collide
 * with its own. AgentsApp sets it from its `base` prop before anything below it
 * fetches, and every component reaches the routes through these two calls. */
let base = ''

export function setBase(b: string) {
  base = (b || '').replace(/\/$/, '')
}

export async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(base + url + (url.includes('?') ? '&' : '?') + 't=' + Date.now())
  if (!res.ok) throw new Error(url + ' -> ' + res.status)
  return res.json()
}

export async function postJSON(url: string, body?: unknown): Promise<unknown> {
  const res = await fetch(base + url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
  const data = await res.json().catch(() => ({}))
  // An agent that refuses a change answers with why. Surfacing its own sentence
  // matters more here than anywhere else on the page: "07:00 is inside the
  // working day" is the whole explanation, and "400" is none of it.
  if (!res.ok) throw new Error(data.error || (url + ' -> ' + res.status))
  return data
}
