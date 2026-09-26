import { useEffect, useRef, useState } from 'react'
import { Alert, Button, SegmentedControl, Spinner, Stat } from '@tiagopedras/tenon'
import { allTargets, hh } from '../lib'
import type { State, View } from '../types'

/* Nothing on this page is fast. /state.json runs every agent's state command,
 * each of which shells out to git in every repo it serves, and a write is
 * followed by a fresh read of all of it. So every wait says so, and the three
 * shapes are the whole vocabulary: the cover on first load, the strip along the
 * top for a write, and a pulse on the one control that was clicked.
 */

/* The strip creeps to 92% over eight seconds and only reaches the end when the
 * answer does. It cannot know how far along it is: there is one request, and it
 * has either come back or it has not. So it eases out and slows down, which is
 * what a wait of unknown length looks like. */
export function ProgressBar({ active }: { active: boolean }) {
  const bar = useRef<HTMLDivElement>(null)
  const was = useRef(false)

  useEffect(() => {
    const el = bar.current
    if (!el) return
    if (active && !was.current) {
      el.className = ''
      // Read a layout property so the browser commits the width-0 start before
      // the class that animates away from it. Without it both land in one
      // frame and the strip appears already finished.
      void el.offsetWidth
      el.className = 'go'
    } else if (!active && was.current) {
      el.className = 'end'
    }
    was.current = active
  }, [active])

  return <div id="bar" ref={bar} />
}

// The cover goes once, on whichever of the first load's outcomes arrives —
// drawn or failed. A page that cannot reach the helper still has to show the
// message saying so.
export function Boot({ done }: { done: boolean }) {
  const [gone, setGone] = useState(false)
  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => setGone(true), 320)
    return () => clearTimeout(t)
  }, [done])
  if (gone) return null
  return (
    <div className={'boot' + (done ? ' gone' : '')}>
      <Spinner size="lg" label="Loading" />
      <p className="bootmsg">Asking each agent what it is doing…</p>
    </div>
  )
}

// What the strip's tones are called in Tenon.
const STAT_TONE = { ok: 'success', ride: 'success', stop: 'warning', bad: 'error' } as const

/* Worked out by the helper across every agent, because the question this page
 * is opened to answer is what is running tonight and an answer split into one
 * row per agent would make the reader add up. Hidden in dash.css: every number
 * it carries is written once on the agent it belongs to, so the strip was the
 * same arithmetic a second time at the top of the page. */
export function Strip({ state }: { state: State | null }) {
  return (
    <section className="strip">
      {(state?.strip || []).map((c, i) => (
        <Stat key={i} eyebrow={c.k} value={c.v} caption={c.w || undefined}
          tone={STAT_TONE[(c.cls || '') as keyof typeof STAT_TONE] || 'default'} />))}
    </section>
  )
}

export function Header({ state, view, onView, title = 'Agents Dashboard' }: {
  state: State | null; view: View; onView: (v: View) => void; title?: string
}) {
  let sub = 'Looking for agents…'
  if (state) {
    const agents = state.agents || []
    const running = agents.filter((a) => a.running)
    sub = running.length
      ? running.map((a) => a.name).join(', ') + (running.length === 1 ? ' is' : ' are') + ' running right now.'
      : `${agents.length} agents · ${allTargets(state).length} targets · it is ${hh(state.hour)}:00`
  }
  // Two readings of the same state, not two pages. The cards answer "what is
  // each of these and is it running on its own", which is what the page is
  // usually opened for. The list puts every agent on one hour scale, which
  // answers "what is running tonight and does anything collide" and gets in the
  // way of everything else. The choice is remembered per browser; the cards are
  // what the page opens on.
  return (
    <div className="top">
      <div className="titles">
        <h1>{title}</h1>
        <p className="topsub">{sub}</p>
      </div>
      <SegmentedControl<View>
        aria-label="View"
        value={view}
        onChange={onView}
        options={[{ value: 'cards', label: 'Cards' }, { value: 'list', label: 'List' }]}
      />
    </div>
  )
}

export function Problem({ message, onDismiss }: { message: string | null; onDismiss: () => void }) {
  if (!message) return null
  return (
    <Alert tone="error" className="problem" actions={<Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button>}>
      {message}
    </Alert>
  )
}
