import { useDash } from '../ctx'
import { hh, markRight } from '../lib'
import type { Load, State } from '../types'

/* The ruler along the top, and the only place an hour is written down.
 *
 * It sits above every panel rather than inside one, and stays there while the
 * page scrolls, because an overlap can be between two targets of one agent or
 * between two agents, and a ruler per panel would have treated the second kind
 * as somebody else's problem. Every panel is the same width and the hour track
 * is the same width inside all of them, so one ruler lines up with every row
 * on the page.
 *
 * Each column carries the count as well as the hour, which answers "is anything
 * doubled up tonight" without reading a single row.
 */
export function Ruler({ state, load }: { state: State; load: Load }) {
  const { hover, syncHours } = useDash()
  const now = state.hour
  const peak = Math.max(0, ...load.count)
  const peakHours = load.count
    .map((n, h) => (n === peak && peak > 0 ? hh(h) + ':00' : null)).filter(Boolean)

  return (
    <div className="rulerwrap">
      <div className="ruler">
        <div className="rlead">
          {peak >= 2 ? (
            <>
              <span className={'rpeak c' + Math.min(peak, 4)}>{peak} at once</span>
              <span className="rwhy">at {peakHours.join(', ')}</span>
            </>
          ) : (
            <>
              <span className="rpeak">No overlaps</span>
              <span className="rwhy">{peak ? 'one at a time all night' : 'nothing is armed'}</span>
            </>
          )}
        </div>
        <div className="hours ruled" onScroll={(e) => syncHours(e.currentTarget.scrollLeft)}>
          {load.count.map((n, h) => {
            const cls = ['rh']
            if (h === now) cls.push('now')
            if (n >= 2) cls.push('c' + Math.min(n, 4))
            else if (n === 1) cls.push('one')
            if (h === hover) cls.push('hl')
            const tip = n
              ? n + ' at ' + hh(h) + ':00 — ' + load.who[h].join(', ')
              : 'nothing armed at ' + hh(h) + ':00'
            return (
              <div key={h} className={cls.join(' ')} data-h={h} title={tip}>
                <span className="l">{hh(h)}</span><span className="n">{n || ''}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/* Where the five-hour usage windows opened, drawn down the whole stack of rows.
 *
 * A window is anchored to whenever its first request landed rather than to the
 * hour grid, so a boundary falls inside a block and not between two of them.
 * That is what makes it a mark of its own rather than a class on a block: the
 * line sits at its real fraction across the block it lands in, and the block it
 * crosses still reads as armed or free underneath it.
 *
 * Today's boundaries only. The track is twenty-four blocks from 00:00 of the
 * day the page is showing, and a mark from last night has nowhere on it to sit
 * that would not be a claim about tonight.
 */
export function windowMarks(s: State) {
  const today = new Date(s.now || Date.now())
  const marks = (s.boundaries || []).flatMap((b, i) => {
    const at = new Date(b.at)
    if (isNaN(at.getTime()) || at.toDateString() !== today.toDateString()) return []
    const label = hh(at.getHours()) + ':' + hh(at.getMinutes())
    const tip = 'A five-hour window opened at ' + label + (b.why ? ' · ' + b.why : '')
    return [
      <i key={i} className="wmark" style={{ right: markRight(at.getHours(), at.getMinutes()) }} title={tip}>
        <b>{label}</b>
      </i>,
    ]
  })
  return marks
}

/* The moment it is now, drawn down the whole stack the same way a window
 * boundary is.
 *
 * The `.now` class on a block says which hour it is, once per row. This says
 * where in that hour, once for the page, so how far tonight has got can be read
 * off a single line rather than found again in every panel.
 *
 * It carries no label, so it takes none of the `.marked` room above the stack;
 * the ruler already names the hour it falls in.
 */
export function NowMark({ state }: { state: State }) {
  const at = new Date(state.now || Date.now())
  if (isNaN(at.getTime())) return null
  return <i className="nowmark" style={{ right: markRight(at.getHours(), at.getMinutes()) }} />
}
