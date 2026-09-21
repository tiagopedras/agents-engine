/* The arithmetic over agents' schedules that draws nothing.
 *
 * What runs when, what collides, what an agent will do tonight, and how a run
 * or an estimate reads in words. The agents dashboard draws all of it, and any
 * other app monitoring agents gets the same answers by importing this rather
 * than working them out again.
 */

export const hh = (h) => String(h).padStart(2, '0')

// What an agent is addressed by. Its id while that id is its own, and its id
// plus where it was found once a second folder claims the same one — a copied
// repo is a whole second agent, descriptor and id included, and routing a
// switch on the id alone reached whichever the server's walk found first. The
// server stamps the key on every card; the fallback is for nothing but an older
// one still answering on the same port.
export const keyOf = (a) => (a && (a.key || a.id)) || ''

// One target, held by agent and target, for anything kept per row.
export const rowKey = (agentKey, targetId) => agentKey + ' :: ' + targetId

// Every target, flattened, each carrying the agent it belongs to. The hour
// arithmetic and anything drawing a whole day want this, and working it out in
// three loops is how the three would drift apart.
export function allTargets(s) {
  const out = []
  ;((s && s.agents) || []).forEach((a) => (a.targets || []).forEach((t) => out.push({ agent: a, target: t })))
  return out
}

// Alphabetical, so two views of the same targets never disagree about order,
// and a row keeps its place whatever its switch is doing.
export const byName = (targets) => (targets || []).slice().sort((a, b) =>
  (a.name || '').localeCompare(b.name || '', undefined, { numeric: true, sensitivity: 'base' }))

/* --- hours ------------------------------------------------------------ */

/* How many targets are armed at each hour, and which ones.
 *
 * Only targets that would actually run count: one that is switched off is not
 * competing for anything, so switching it off has to relieve the warning rather
 * than leave it sitting there. A target whose agent's launchd job is not loaded
 * does not count either — its schedule says when it would run, not when it will.
 */
export function loadByHour(s) {
  const count = new Array(24).fill(0)
  const who = Array.from({ length: 24 }, () => [])
  allTargets(s).forEach(({ agent, target }) => {
    if (!target.on) return
    if (agent.job && agent.job.loaded === false) return
    ;(target.hours || []).forEach((h) => {
      if (h >= 0 && h < 24) { count[h] += 1; who[h].push(target.name) }
    })
  })
  return { count, who }
}

/* Twenty-four booleans folded into the stretches they make, wrapping midnight.
 *
 * Contiguity is worked out rather than assumed — a schedule with a hole in it
 * says so, as two stretches, instead of being flattened into one that would be
 * a lie about the hours in between.
 */
export function hourRanges(hours) {
  const set = new Array(24).fill(false)
  ;(hours || []).forEach((h) => { if (h >= 0 && h < 24) set[h] = true })
  if (!set.some(Boolean)) return []
  const runs = []
  for (let h = 0; h < 24; h++) {
    if (!set[h]) continue
    if (runs.length && runs[runs.length - 1].to === h - 1) runs[runs.length - 1].to = h
    else runs.push({ from: h, to: h })
  }
  // A night is one stretch across midnight, not a stretch ending at 23:00 and
  // another starting at 00:00. Only ever merges when both ends are held and
  // there is more than one of them.
  if (runs.length > 1 && set[23] && set[0]) {
    const last = runs.pop()
    runs[0] = { from: last.from, to: runs[0].to }
  }
  return runs
}

// "19:00–02:00", or "03:00 and 05:00–06:00". Empty for no hours.
export function rangeText(hours) {
  const runs = hourRanges(hours)
  if (!runs.length) return ''
  return runs.map((r) => (r.from === r.to ? hh(r.from) + ':00'
    : hh(r.from) + ':00–' + hh(r.to) + ':00')).join(' and ')
}

/* The next hour any of these targets could start in, said against now.
 *
 * "03:00" on its own is ambiguous at 04:00 — it reads as an hour that
 * has just gone by — so the answer always carries which side of midnight it
 * falls on. An hour that is the current one is "due this hour" rather than a
 * time, because the wake for it has either already happened or is minutes away.
 */
export function nextStart(armed, now) {
  const set = new Set()
  armed.forEach((t) => (t.hours || []).forEach((h) => set.add(h)))
  if (!set.size) return ''
  if (set.has(now)) return 'due this hour'
  for (let i = 1; i <= 24; i++) {
    const h = (now + i) % 24
    if (!set.has(h)) continue
    return hh(h) + ':00 ' + (now + i < 24 ? 'today' : 'tomorrow')
  }
  return ''
}

const cap = (text) => (text ? text[0].toUpperCase() + text.slice(1) : text || '')

/* One sentence for whether this agent does anything without being asked.
 *
 * Five answers and they are not degrees of one thing, which is why this is not
 * a count. Planned is work that does not exist yet. Built is an agent that
 * exists and has no schedule to keep, so the honest sentence is what starts it
 * rather than when. Held back is a schedule launchd is not carrying, so the
 * hours are a plan rather than a fact. Nothing armed is switches, which is his
 * own doing and reads as normal. Only the last one is an agent that will spend
 * money tonight.
 */
export function autonomy(agent, now) {
  if (agent.reference) {
    return {
      tone: 'plan',
      head: cap(agent.cadence || 'on demand'),
      text: agent.kind === 'built'
        ? (agent.started_by || 'it runs when you start it, never on its own')
        : 'nothing built yet',
    }
  }
  if (agent.broken) return { tone: 'bad', head: 'Unknown', text: 'it is not answering' }
  const withHours = (agent.targets || []).filter((t) => (t.hours || []).length)
  if (!withHours.length) {
    return { tone: 'plan', head: 'On demand', text: 'it runs when you start it, never on its own' }
  }
  const armed = withHours.filter((t) => t.on)
  if (agent.job && agent.job.loaded === false) {
    return {
      tone: 'bad',
      head: 'Held back',
      text: 'launchd is not carrying the wake, so none of the hours below will fire',
    }
  }
  if (!armed.length) {
    return { tone: 'off', head: 'Nothing armed', text: 'every switch below is off, so nothing starts on its own' }
  }
  // Which one goes next, and nothing else: the count of what is armed and the
  // hours they are armed at are already one line per target.
  return { tone: 'ok', head: 'Next run', text: nextStart(armed, now), kv: true }
}

export function jobLine(agent) {
  const j = agent.job
  if (!j) return { cls: '', text: '' }
  if (j.loaded) return { cls: 'ok', text: 'Armed · launchd has the hourly wake loaded' }
  if (j.installed) {
    return { cls: 'bad', text: 'Not loaded · the plist is linked but launchctl has not loaded it' }
  }
  return { cls: 'bad', text: 'Not installed · see the agent’s README — one symlink and one launchctl load' }
}

/* --- runs --------------------------------------------------------------- */

/* The last run in one line. What it built, what it folded and on which branch
 * are three lines each, and this is one. */
export function runLine(run) {
  if (run === undefined) return null
  if (!run) return { text: 'no run yet', empty: true }
  if (run.skipped) return { text: `${run.when || ''} · ${run.skipped}` }
  const rows = run.rows || []
  const built = rows.filter((r) => r.tone === 'good').length
  const said = rows.length ? `${built} of ${rows.length} built` : 'nothing attempted'
  const head = [run.when, run.meta].filter(Boolean).join(' · ')
  return { text: `${head}${head ? ' · ' : ''}${said}` }
}

// Zero when there has been no run yet or the last one was skipped.
export function builtLastRun(run) {
  return run && !run.skipped ? (run.rows || []).filter((r) => r.tone === 'good').length : 0
}

/* What the last run built, counted only when that run was inside the past day.
 * A run from three nights ago built nothing last night, so it says zero rather
 * than repeating an old number under a new label. A run that was skipped, or an
 * agent that reports no runs, has no count to give. */
export function builtLastNight(run, now = Date.now()) {
  if (!run || run.skipped) return null
  const at = Date.parse(String(run.when || '').replace(' ', 'T'))
  if (Number.isNaN(at) || now - at > 24 * 3600 * 1000) return 0
  return builtLastRun(run)
}

/* --- the status vocabulary --------------------------------------------- */

/* The six states of PACKAGES/work-streams/CONTRACT.md, in the order work runs
 * through them, and the label and tone to fall back to for each.
 *
 * Copied from there because a browser cannot read the Python module that owns
 * it. What it must not become is a second opinion: a name added there and not
 * here shows up as a card declined rather than a card classified wrongly.
 *
 * A card's `state` stays the agent's own word and is what gets printed. The
 * label below is for an agent that sends a status and no word of its own.
 */
export const STATUS = {
  backlog: { label: 'Backlog', tone: null },
  ready: { label: 'Ready', tone: 'good' },
  doing: { label: 'Doing', tone: 'good' },
  review: { label: 'Review', tone: 'warn' },
  blocked: { label: 'Blocked', tone: 'warn' },
  done: { label: 'Done', tone: null },
}
export const STATUSES = Object.keys(STATUS)

// A status not in the list is no status: the card draws as it always did.
// Dropping it instead would hide work.
export const statusOf = (c) => (c && c.status && STATUS[c.status] ? c.status : null)

export const cardLabel = (c) => {
  const st = statusOf(c)
  return c.state != null ? c.state : (st ? STATUS[st].label : '')
}

/* What one card is expected to cost, as the agent worked it out: a range with
 * the number of past runs beside it, never a bare figure that reads as a price. */
export function estimateText(e) {
  if (!e) return ''
  const unit = e.unit == null ? '$' : e.unit
  const money = (v) => unit + Number(v).toFixed(2)
  const n = Number(e.n) || 0
  const span = e.low == null || e.high == null ? ''
    : (Number(e.low) === Number(e.high) ? money(e.low) : `${money(e.low)}–${money(e.high)}`)
  const from = n ? `${n} past run${n === 1 ? '' : 's'}` : 'nothing like it has run yet'
  return span ? `${span} · ${from}` : from
}
