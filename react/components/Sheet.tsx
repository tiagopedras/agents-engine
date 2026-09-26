import { useState } from 'react'
import { Card, Modal, Pill, SegmentedControl } from '@tiagopedras/tenon'
import { allTargets, cardLabel, estimateText, keyOf, relTime, STATUS, STATUSES, statusOf } from '../lib'
import type { DetailCard, DetailGroup, State } from '../types'
import { RunRows, toneOf } from './TargetRow'

export type SheetKind =
  | { kind: 'detail'; agent: string; target: string; status?: string }
  | { kind: 'log'; agent: string }
  | { kind: 'built'; agent: string; target: string }

/* One sheet, three things in it: a target's detail, opened from one of its
 * numbers, an agent's log, opened from the button in its status band, and what
 * a target's last run built, opened from the tag on its card line.
 * Nothing else on this page opens a modal. Tenon's Modal does the scrim, the
 * focus trap, Escape, and putting focus back on whatever opened it.
 */
export function Sheet({ sheet, state, onClose }: { sheet: SheetKind | null; state: State; onClose: () => void }) {
  let title = ''
  let body: React.ReactNode = null

  if (sheet?.kind === 'detail') {
    const found = allTargets(state).find((x) => keyOf(x.agent) === sheet.agent && x.target.id === sheet.target)
    const detail = found?.target.detail
    if (found && detail) {
      title = detail.title || found.target.name
      body = <DetailBody groups={(detail.groups || []).filter((g) => (g.cards || []).length)} initial={sheet.status} />
    }
  } else if (sheet?.kind === 'built') {
    const found = allTargets(state).find((x) => keyOf(x.agent) === sheet.agent && x.target.id === sheet.target)
    const run = found?.target.last_run
    if (found && run && !run.skipped) {
      const built = (run.rows || []).filter((r) => r.tone === 'good')
      title = found.target.name + ' · built last night'
      body = (
        <>
          <p className="run"><span className="when" title={run.when}>{[relTime(run.when), run.meta].filter(Boolean).join(' · ')}</span></p>
          {built.length ? <RunRows rows={built} /> : <p className="empty">Nothing was built.</p>}
        </>
      )
    }
  } else if (sheet?.kind === 'log') {
    const agent = (state.agents || []).find((a) => keyOf(a) === sheet.agent)
    if (agent) {
      title = agent.name + ' · log'
      body = <pre className="logpre"><Linked text={(agent.log || []).join('\n').trim() || 'Nothing logged yet.'} /></pre>
    }
  }

  return <Modal open={!!body} onClose={onClose} title={title} size="lg" className="agents-ui">{body}</Modal>
}

/* Log text with every web address in it made a link. Punctuation at the end of
 * an address is left out of it, since a log line that ends a sentence on a URL
 * would otherwise link to a page with a full stop on the end.
 */
const URL_RE = /https?:\/\/[^\s<>"'`]+/g

function Linked({ text }: { text: string }) {
  const out: React.ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(URL_RE)) {
    const url = m[0].replace(/[.,;:!?)\]}]+$/, '')
    const start = m.index!
    out.push(text.slice(last, start))
    out.push(<a key={start} href={url} target="_blank" rel="noopener noreferrer">{url}</a>)
    last = start + url.length
  }
  out.push(text.slice(last))
  return <>{out}</>
}

function DetailEntry({ c }: { c: DetailCard }) {
  const st = statusOf(c)
  const label = cardLabel(c)
  const tone = c.tone || (st && STATUS[st].tone) || undefined
  return (
    <Card className={'ecard' + (c.done || st === 'done' ? ' isdone' : '')}>
      <div className="etop">
        {(c.tags || []).map((t) => <Pill key={t} caps>{t}</Pill>)}
        {label ? <Pill tone={toneOf(tone)} caps>{label}</Pill> : null}
        {c.index ? <span className="eidx">#{c.index}</span> : null}
      </div>
      <p className="elead">{c.text}</p>
      {c.why && <p className="ewhy">{c.why}</p>}
      {c.estimate && <p className="ecost">{estimateText(c.estimate)}</p>}
    </Card>
  )
}

/* The row of filters over a sheet, one chip per status actually in it.
 *
 * Drawn from what is there rather than from the whole vocabulary, since a chip
 * for a status with nothing under it is a button whose only outcome is an empty
 * sheet. Two is the smallest number worth drawing: a sheet whose every card is
 * the same status is already filtered.
 *
 * The agent's own groups stay the grouping. This narrows what is on screen
 * inside them, which is the one thing a reader cannot do by choosing a number.
 * A number that counts a status opens the sheet already narrowed to it, but
 * only when the sheet drew a chip for it.
 */
function DetailBody({ groups, initial }: { groups: DetailGroup[]; initial?: string }) {
  const n = (s: string) => groups.reduce((sum, g) => sum + g.cards.filter((c) => statusOf(c) === s).length, 0)
  const present = STATUSES.map((s) => [s, n(s)] as const).filter(([, count]) => count)
  const chips = present.length >= 2
  const [filter, setFilter] = useState(chips && initial && present.some(([s]) => s === initial) ? initial : 'all')

  if (!groups.length) return <p className="empty">Nothing to show.</p>

  return (
    <>
      {chips && (
        <div className="efilter">
          <SegmentedControl
            aria-label="Filter by status"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'All' },
              ...present.map(([s, count]) => ({ value: s, label: `${STATUS[s].label} · ${count}` })),
            ]}
          />
        </div>)}
      {groups.map((g) => {
        // A group's heading carries its own count, so a group narrowed to
        // nothing goes with its cards and a group narrowed to three says three.
        const cards = g.cards.filter((c) => filter === 'all' || statusOf(c) === filter)
        if (!cards.length) return null
        return (
          <div className="egroup" key={g.name}>
            <div className="lbl">{g.name} · <span className="ecount">{cards.length}</span></div>
            <div className="ecards">{cards.map((c, i) => <DetailEntry key={i} c={c} />)}</div>
          </div>
        )
      })}
    </>
  )
}
