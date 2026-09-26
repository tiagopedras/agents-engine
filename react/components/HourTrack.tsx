import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { postJSON } from '../api'
import { useDash } from '../ctx'
import { hh } from '../lib'
import type { Load } from '../types'

interface Props {
  name: string
  hours?: number[]
  load: Load
  armed: boolean
  editable: boolean
  preferred?: number[]
  agentKey: string
  targetId: string
  now: number
}

interface Painted { lo: number; hi: number; next: Set<number> }
interface Drag { from: number; to: number; turnOn: boolean; moved: boolean; pointerId: number; painted: Painted | null }

const CELL = 'button.hr[data-hour]'

/* One target's twenty-four hours.
 *
 * Blank blocks rather than numbered ones. Which hour a column is stands at the
 * top of the page in the ruler, once, and printing it again in every block six
 * rows down spends the width that lets the columns line up at all. What a block
 * has left to say is the only thing worth saying at this size: armed, free,
 * taken by something else, or refused.
 *
 * `armed` says whether this row's own hours are already in the count. For one
 * that is switched off they are not, so the severity it shows is what the hour
 * would become if it were switched on — which is the number worth knowing while
 * deciding whether to switch it on.
 *
 * `preferred` is the set of hours the owning agent would rather run at. An hour
 * outside it is hatched: it takes clicks like any other, and the hatch says
 * only that this is the worse hour to pick. It was a floor until 19 September
 * 2026 — those hours were drawn dead and the planning agent refused to write
 * them — and it came out at his word, since he sets the hours by hand and
 * nothing here works them out for him.
 *
 * A night is a run of hours, and setting one used to be a click per block —
 * twelve clicks and twelve round trips to arm 19:00 to 06:59. So a press and a
 * drag paints the range between the block it started on and the block under the
 * pointer now, and lets go once. What it paints is decided by the block it
 * started on: starting on a free block arms the range, starting on an armed one
 * clears it. That is what makes a drag reversible — the range is recomputed from
 * the schedule each time rather than toggled as you pass.
 *
 * A press with no movement is left alone: it is the click, which still toggles
 * the one block and is still what a keyboard's Enter does. Only a drag
 * suppresses that click.
 */
export function HourTrack({ name, hours, load, armed, editable, preferred, agentKey, targetId, now }: Props) {
  const { act, hover, syncHours } = useDash()
  const track = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const skipClick = useRef(false)
  const alive = useRef(true)
  // The range being painted, drawn without being written.
  const [range, setRange] = useState<Painted | null>(null)
  // A drag's result stays painted until the write and the read after it are back.
  const [held, setHeld] = useState<Set<number> | null>(null)
  // The hours whose write has not come back.
  const [pending, setPending] = useState<Set<number> | null>(null)
  const [nopan, setNopan] = useState(false)

  const set = useMemo(() => new Set(hours || []), [hours])
  const ok = useMemo(() => (preferred ? new Set(preferred) : null), [preferred])
  const waiting = pending !== null

  useEffect(() => () => { alive.current = false }, [])

  // Whether a finger dragged across this track paints hours or scrolls the day.
  // It cannot do both, and on a phone the track is narrower than its
  // twenty-four blocks, so there the swipe is how you reach 23:00 at all and
  // scrolling wins. Where the whole day already fits there is nothing to
  // scroll, so the drag is free to paint. Measured rather than assumed from a
  // breakpoint: what decides it is whether this track overflows.
  useLayoutEffect(() => {
    const el = track.current
    if (!el) return
    const measure = () => setNopan(el.scrollWidth <= el.clientWidth + 1)
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  const write = async (next: number[], marked: Set<number>) => {
    setPending(marked)
    try {
      await act(() => postHours(agentKey, targetId, next))
    } finally {
      if (alive.current) { setPending(null); setHeld(null) }
    }
  }

  const cellAt = (x: number, y: number) => {
    // `elementFromPoint` rather than the event's own target because a pointer
    // with a block captured keeps reporting that block as the target for the
    // whole gesture, which is what makes a drag end cleanly off the end of the
    // track and what would otherwise stop it seeing any block but the first.
    const el = document.elementFromPoint(x, y)
    return el ? (el.closest(CELL) as HTMLElement | null) : null
  }

  const endDrag = () => {
    const d = drag.current
    drag.current = null
    document.body.classList.remove('agents-dragging')
    return d
  }

  const onPointerDown = (ev: React.PointerEvent) => {
    // Cleared here rather than in the click handler: a drag that ends off the
    // end of the track fires no click at all, and a flag left standing would
    // eat the next real one.
    skipClick.current = false
    if (ev.button || waiting) return
    const cell = (ev.target as Element).closest(CELL) as HTMLButtonElement | null
    if (!cell || cell.disabled) return
    const h = Number(cell.dataset.hour)
    drag.current = { from: h, to: h, turnOn: !set.has(h), moved: false, pointerId: ev.pointerId, painted: null }
    try { cell.setPointerCapture(ev.pointerId) } catch { /* mouse is fine without */ }
  }

  const onPointerMove = (ev: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const cell = cellAt(ev.clientX, ev.clientY)
    // Another row's track is somebody else's schedule. Leaving the track mid-drag
    // holds the range where it was rather than cancelling, so running off the
    // bottom edge and coming back is not a lost gesture.
    if (!cell || cell.closest('.hours') !== track.current) return
    const h = Number(cell.dataset.hour)
    if (h === d.to && d.moved) return
    d.to = h
    if (!d.moved && h === d.from) return
    d.moved = true
    document.body.classList.add('agents-dragging')
    // Built from `set`, the hours as the agent last reported them, rather than
    // from what is on screen: a range that shrinks has to put the blocks it no
    // longer covers back, and only the untouched schedule knows what they were.
    const lo = Math.min(d.from, d.to)
    const hi = Math.max(d.from, d.to)
    const next = new Set(set)
    for (let i = lo; i <= hi; i++) { if (d.turnOn) next.add(i); else next.delete(i) }
    d.painted = { lo, hi, next }
    setRange(d.painted)
  }

  const onPointerUp = (ev: React.PointerEvent) => {
    const d = endDrag()
    try { (ev.target as Element).releasePointerCapture(ev.pointerId) } catch { /* already gone */ }
    const painted = d?.painted
    if (!d || !d.moved || !painted) { setRange(null); return }
    // The click that follows a drag would toggle the block it started on a
    // second time, undoing one end of what was just painted.
    skipClick.current = true
    const marked = new Set<number>()
    for (let i = painted.lo; i <= painted.hi; i++) marked.add(i)
    setHeld(painted.next)
    setRange(null)
    void write([...painted.next].sort((a, b) => a - b), marked)
  }

  const onPointerCancel = () => {
    // Nothing was written, so the track goes back to the schedule.
    endDrag()
    setRange(null)
  }

  const toggle = (h: number) => {
    // A drag has already written the whole range; this is its trailing click.
    if (skipClick.current) { skipClick.current = false; return }
    if (waiting) return
    const next = new Set(set)
    if (next.has(h)) next.delete(h); else next.add(h)
    // Marked before the write rather than after the redraw. The round trip is a
    // write through the agent followed by a read of every agent's state, and
    // for those couple of seconds a block that does not move reads as a click
    // that missed. The rest of the row stops taking clicks while this one is
    // out, because the write sends the whole set of hours and a second click
    // would send a set built from a schedule already being replaced.
    void write([...next].sort((a, b) => a - b), new Set([h]))
  }

  const cells = []
  for (let h = 0; h < 24; h++) {
    const picked = set.has(h)
    const shownOn = range ? range.next.has(h) : held ? held.has(h) : picked
    const barred = ok ? !ok.has(h) : false
    const total = load.count[h] + (picked && !armed ? 1 : 0)
    const cls = ['hr']
    if (barred) cls.push('barred')
    if (shownOn) cls.push('on')
    if (range && h >= range.lo && h <= range.hi) cls.push('painting')
    if (pending && pending.has(h)) cls.push('pending')
    if (h === now) cls.push('now')
    if (h === hover) cls.push('hl')
    // Severity only on an hour this row actually holds: an overlap is two
    // things both running then, and an hour this one has not picked is not one
    // of them. An hour with something else in it still gets the dashed hint,
    // which is what makes a free slot findable when picking one.
    if (picked && total >= 2) cls.push('clash', 'c' + Math.min(total, 4))
    else if (!picked && load.count[h] > 0) cls.push('busy')

    const names = load.who[h].filter((n) => n !== name)
    // Every block names its own hour, because the block no longer prints one.
    let tip = hh(h) + ':00 · ' + name + (picked ? ' is armed' : ' is not armed')
    if (barred) {
      tip = hh(h) + ':00 is inside the working day — this agent would rather run'
        + ' at night, but it will run at this hour if you set it'
    } else if (picked && total >= 2) {
      // An unarmed row's count is what the hour would become, not what it is,
      // and saying it the other way would report a clash that is not happening.
      tip = armed
        ? total + ' at ' + hh(h) + ':00 — ' + [name].concat(names).join(', ')
        : total + ' at ' + hh(h) + ':00 if this were switched on — ' + [name].concat(names).join(', ')
    } else if (names.length) {
      tip += ' · already here: ' + names.join(', ')
    }

    cells.push(editable
      ? <button key={h} type="button" className={cls.join(' ')} data-hour={h} data-h={h}
          title={tip} aria-label={tip} onClick={() => toggle(h)} />
      : <span key={h} className={cls.join(' ')} data-h={h} title={tip} />)
  }

  return (
    <div
      ref={track}
      className={'hours' + (nopan ? ' nopan' : '') + (waiting ? ' waiting' : '')}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onScroll={(e) => syncHours(e.currentTarget.scrollLeft)}
    >
      {cells}
    </div>
  )
}

function postHours(agent: string, target: string, hours: number[]) {
  return postJSON('/apply', { agent, target, changes: { hours } })
}
