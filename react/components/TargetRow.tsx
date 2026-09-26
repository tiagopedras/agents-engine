import { Fragment, useEffect, useRef, useState } from 'react'
import { Button, DragHandle, Field, Pill, Switch } from '@tiagopedras/tenon'
import type { ReorderItem } from '@tiagopedras/tenon'
import { postJSON } from '../api'
import { useDash } from '../ctx'
import { builtLastRun, keyOf, relRun, relTime, rowKey, runLine, STATUS } from '../lib'
import type { Agent, Count, Field as FieldT, Load, RunRow, Target } from '../types'
import { HourTrack } from './HourTrack'
import { ActionButton } from './ActionButton'

export const TONE = { good: 'success', warn: 'warning', bad: 'error' } as const
export const toneOf = (t?: string) => (t && t in TONE ? TONE[t as keyof typeof TONE] : 'neutral')

// A target name like PACKAGES/ai_chat_engine has no spaces in it, so a row too
// narrow to hold it broke it wherever the line ran out — "ai_chat_engi / ne".
// A <wbr> after each slash, underscore and hyphen gives the browser a break it
// can take that reads as a path rather than as a typo, so a long name wraps
// where its own words join rather than in the middle of one.
function NameBreaks({ text }: { text: string }) {
  return <>{text.split(/([/_-])/).map((part, i) => (
    /^[/_-]$/.test(part) ? <Fragment key={i}>{part}<wbr /></Fragment> : part))}</>
}

/* A target's faults, collapsed to one bell beside its name.
 *
 * Three of these used to be three full-width boxes of prose stacked through the
 * middle of the card, which pushed the hour grid and the fields off the screen
 * on the one target that most needed looking at. The count is the whole summary;
 * the sentences are one click away and unchanged.
 *
 * Target faults only. Launchd not being armed and a STOP usage window stop every
 * target rather than one, and they keep reporting themselves in the agent's own
 * band, which is where they are read.
 */
export function Bell({ problems, name }: { problems?: string[]; name: string }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDetailsElement>(null)

  // `details` closes on its own summary and nowhere else, so an outside click
  // and Escape are added here.
  useEffect(() => {
    if (!open) return
    const away = (ev: MouseEvent) => {
      if (box.current && !box.current.contains(ev.target as Node)) setOpen(false)
    }
    const esc = (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape') return
      setOpen(false)
      box.current?.querySelector('summary')?.focus()
    }
    document.addEventListener('click', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('click', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  if (!problems || !problems.length) return null
  const n = problems.length
  return (
    <details ref={box} className="bell" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary aria-label={`${n} problem${n === 1 ? '' : 's'} with ${name}`}>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"
          strokeLinejoin="round" aria-hidden="true">
          <path d="M4.2 6.6a3.8 3.8 0 0 1 7.6 0c0 3 1 3.7 1.4 4.2H2.8c.4-.5 1.4-1.2 1.4-4.2Z" />
          <path d="M6.4 12.4a1.7 1.7 0 0 0 3.2 0" />
        </svg>
        <span className="bn">{n}</span>
      </summary>
      <div className="pop">{problems.map((p, i) => <p key={i}>{p}</p>)}</div>
    </details>
  )
}

/* The on/off switch for one target, the same in a row and on a card line. A
 * target that cannot be switched shows its state as a word instead. */
export function TargetSwitch({ target, agentKey }: { target: Target; agentKey: string }) {
  const { act } = useDash()
  const [flipping, setFlipping] = useState(false)

  const flip = async () => {
    setFlipping(true)
    try {
      await act(() => postJSON('/apply', { agent: agentKey, target: target.id, changes: { on: !target.on } }))
    } finally { setFlipping(false) }
  }

  if (target.switchable === false) return <span className="swfixed">{target.on ? 'ON' : 'off'}</span>
  return (
    <Switch checked={!!target.on} className={flipping ? 'pending' : ''}
      aria-label={`switch ${target.name} ${target.on ? 'off' : 'on'}`} onChange={flip} />
  )
}

/* Takes a target off this page. Nothing changes in the agent: the target stays
 * armed and keeps running, and the agent's "Hidden" link brings it back. */
export function HideButton({ target, agentKey }: { target: Target; agentKey: string }) {
  const { setHidden } = useDash()
  return (
    <Button variant="ghost" size="sm" iconOnly className="hide" title="Hide from this page"
      aria-label={`hide ${target.name}`} onClick={() => setHidden(rowKey(agentKey, target.id), true)}>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M2 8s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4Z" />
        <circle cx="8" cy="8" r="1.7" />
        <path d="M3 13 13 3" />
      </svg>
    </Button>
  )
}

function CountView({ c, target, agentKey, cls }: { c: Count; target: Target; agentKey: string; cls: string }) {
  const { openDetail } = useDash()
  const inner = <><span className="n">{c.n}</span><span className="l">{c.l}</span></>
  // A count that says which status it counts opens the sheet already narrowed
  // to it, so the number and the list under it agree. Without one the sheet
  // opens whole, which is what every count did before there were statuses.
  const status = c.status && STATUS[c.status] ? c.status : undefined
  // A zero that names its status would open a sheet with nothing to narrow to.
  const opens = c.opens && !(status && !Number(c.n))
  return opens
    ? <button type="button" className={cls} aria-haspopup="dialog" title={c.title || ''}
        onClick={() => openDetail(agentKey, target.id, status)}>{inner}</button>
    : <span className={cls}>{inner}</span>
}

/* The numbers that survive into the row itself.
 *
 * An agent tags its own counts, `good` and `warn`, and those two are the ones
 * worth carrying at this size: how much can be built, and how much is waiting on
 * him. Each opens the sheet narrowed to what it counts. The total stays in the
 * disclosure. An agent that tags nothing gets its first two, so a third agent
 * written to no plan still draws something. Last in the row is what the last run
 * built, which is the same arithmetic as the run line under the name.
 */
function MiniCounts({ target, agentKey }: { target: Target; agentKey: string }) {
  const { openBuilt } = useDash()
  const counts = target.counts || []
  const kinds: Record<string, string> = { good: 'build', warn: 'needs' }
  let use = counts.filter((c) => c.kind && kinds[c.kind])
  if (!use.length && !counts.some((c) => c.kind)) use = counts.slice(0, 2)
  const ran = target.last_run !== undefined
  if (!use.length && !ran) return null
  // Pending means the run built something nobody has looked at yet, so the tag
  // takes the warn colour rather than the neutral one and opens the sheet.
  const built = (target.last_run?.rows || []).some((r) => r.tone === 'good')
  return (
    <span className="minis">
      {use.map((c, i) => (
        <CountView key={i} c={c} target={target} agentKey={agentKey}
          cls={'count ' + (c.kind ? kinds[c.kind] || '' : '')} />))}
      {ran && (
        built ? (
          <button type="button" className="count ran pending" aria-haspopup="dialog"
            title="What this run built" onClick={() => openBuilt(agentKey, target.id)}>
            <span className="n">{builtLastRun(target.last_run)}</span><span className="l">built last run</span>
          </button>
        ) : (
          <span className="count ran">
            <span className="n">{builtLastRun(target.last_run)}</span><span className="l">built last run</span>
          </span>
        )
      )}
    </span>
  )
}

function CountsRow({ target, agentKey }: { target: Target; agentKey: string }) {
  const counts = target.counts || []
  if (!counts.length) return null
  const kinds: Record<string, string> = { total: 'total', good: 'build', warn: 'needs' }
  return (
    <div className="counts">
      {counts.map((c, i) => (
        <CountView key={i} c={c} target={target} agentKey={agentKey}
          cls={'count big ' + (c.kind ? kinds[c.kind] || '' : '')} />))}
    </div>
  )
}

/* The last run in full, for the row's own disclosure and for a card. */
export function RunRows({ rows }: { rows: RunRow[] }) {
  return <>{rows.map((r, i) => (
    <div className="ent" key={i}>
      <Pill tone={toneOf(r.tone)} caps>{r.label == null ? '—' : r.label}</Pill>
      <span className="lead">{r.text}</span>
      {r.tag ? <span className="br">{r.tag}</span> : null}
    </div>))}</>
}

function LastRunView({ target }: { target: Target }) {
  const run = target.last_run
  if (!run) return <p className="empty">No run yet.</p>
  if (run.skipped) {
    return <p className="run"><span className="when" title={run.when}>{relTime(run.when)}</span> — {run.skipped}</p>
  }
  const head = [relTime(run.when), run.meta].filter(Boolean).join(' · ')
  return (
    <>
      <p className="run"><span className="when" title={run.when}>{head}</span></p>
      {run.rows && run.rows.length ? <RunRows rows={run.rows} /> : <p className="empty">Nothing attempted.</p>}
    </>
  )
}

/* One setting an agent declared editable. Written when the box loses focus and
 * its text is not what it held when it gained it, which is what the browser's
 * own `change` event meant before this was a component. Uncontrolled, and keyed
 * on the value the agent reported, so a redraw that brings a new value replaces
 * the box and one that brings the same value leaves whatever is being typed
 * alone. */
function FieldView({ f, agentKey, targetId }: { f: FieldT; agentKey: string; targetId: string }) {
  const { act } = useDash()
  const at = useRef('')
  const value = f.type === 'lines' ? ((f.value as string[]) || []).join('\n') : String(f.value == null ? '' : f.value)

  const commit = (el: HTMLInputElement | HTMLTextAreaElement) => {
    if (el.value === at.current) return
    at.current = el.value
    const sent = f.type === 'number' ? Number(el.value) : el.value
    void act(() => postJSON('/apply', { agent: agentKey, target: targetId, changes: { [f.key]: sent } }))
  }

  // What this number is about to buy, said where the number is set. The page
  // cannot work it out — only the agent knows what is in reach tonight and what
  // things like it have cost — so the sentence is the agent's and this draws it
  // and nothing else. It rides in the label rather than under the box, so a
  // field carrying one is no taller than the fields beside it and every input on
  // the row stays on the same line.
  const tone = f.headline_tone && ['good', 'warn', 'bad'].includes(f.headline_tone) ? f.headline_tone : ''
  const label = (
    <>{f.label}{f.headline ? <span className={'fnote ' + tone}>{f.headline}</span> : null}</>
  )
  const common = {
    label,
    defaultValue: value,
    onFocus: (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => { at.current = e.currentTarget.value },
    onBlur: (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => commit(e.currentTarget),
    className: f.wide ? 'wide' : undefined,
  }
  const key = f.key + '=' + value

  if (f.type === 'lines') return <Field key={key} multiline rows={f.rows || 2} {...common} />
  return (
    <Field
      key={key}
      type={f.type === 'number' ? 'number' : 'text'}
      min={f.min} max={f.max} step={f.step}
      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
      {...common}
    />
  )
}

function FieldRows({ target, agentKey }: { target: Target; agentKey: string }) {
  const fields = target.fields || []
  if (!fields.length) return null
  // Narrow fields sit several to a row, wide ones take the row. Splitting them
  // here rather than letting the grid do it keeps a wide textarea from being
  // dragged up beside two number boxes.
  const narrow = fields.filter((f) => !f.wide)
  const wide = fields.filter((f) => f.wide)
  return (
    <>
      {narrow.length > 0 && (
        <div className="fields">
          {narrow.map((f) => <FieldView key={f.key} f={f} agentKey={agentKey} targetId={target.id} />)}
        </div>)}
      {wide.length > 0 && (
        <div className="fields" style={{ marginTop: 12 }}>
          {wide.map((f) => <FieldView key={f.key} f={f} agentKey={agentKey} targetId={target.id} />)}
        </div>)}
    </>
  )
}

/* One target: who it is on the left, its day on the right, and everything else
 * folded away underneath until it is asked for. `drag` is only present where a
 * saved order applies — the panel/list view, which has more than one target to
 * sequence per agent. */
export function TargetRow({ target, agent, load, now, drag }: {
  target: Target; agent: Agent; load: Load; now: number; drag?: ReorderItem
}) {
  const { isOpen, toggleOpen } = useDash()
  const agentKey = keyOf(agent)
  const editable = target.hours_editable !== false
  const open = isOpen(rowKey(agentKey, target.id))
  const run = runLine(relRun(target.last_run))

  // The second line under the name. Path, note and last run are each a short
  // phrase, and none of them earns a line of its own in a row this size.
  const meta = [
    target.note ? <span key="note" className="rnote">{target.note}</span> : null,
    run ? <span key="run" className={'rrun' + (run.empty ? ' empty' : '')} title={target.last_run?.when}>{run.text}</span> : null,
  ].filter(Boolean)

  return (
    <section className={'trow ' + (target.on ? 'on' : 'off') + (open ? ' open' : '')}
      {...drag?.itemProps}>
      <div className="rowhead">
        {drag && <DragHandle {...drag.handleProps} />}
        <TargetSwitch target={target} agentKey={agentKey} />
        <div className="rowid">
          <div className="rowname">
            <span className="name"><NameBreaks text={target.name} /></span>
            <Bell problems={target.problems} name={target.name} />
          </div>
          {meta.length > 0 && (
            <div className="rowmeta">
              {meta.map((m, i) => <Fragment key={i}>{i > 0 && <span className="dot">·</span>}{m}</Fragment>)}
            </div>)}
        </div>
        <span className="spacer" />
        <MiniCounts target={target} agentKey={agentKey} />
        <Button variant="ghost" size="sm" iconOnly className="chev" aria-expanded={open}
          aria-label={`settings for ${target.name}`} onClick={() => toggleOpen(rowKey(agentKey, target.id))}>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 6.5 8 10.5 12 6.5" />
          </svg>
        </Button>
        <HideButton target={target} agentKey={agentKey} />
      </div>

      {target.hours
        ? <HourTrack name={target.name} hours={target.hours} load={load} armed={!!target.on}
            editable={editable} preferred={agent.hours_preferred} agentKey={agentKey}
            targetId={target.id} now={now} />
        : <div className="hours nohours"><span className="empty">no schedule</span></div>}

      {(target.actions || []).length > 0 && (
        <div className="racts">
          {(target.actions || []).map((a) => (
            <ActionButton key={a.id} action={a} agentKey={agentKey} targetId={target.id} size="sm" />))}
        </div>
      )}

      {open && (
        <div className="rowbody">
          <CountsRow target={target} agentKey={agentKey} />
          {target.chips && (target.chips.items || []).length > 0 && (
            <>
              <div className="lbl" style={{ marginTop: 14 }}>{target.chips.label}</div>
              <div className="branches">{target.chips.items.map((b) => <span key={b} className="br">{b}</span>)}</div>
            </>)}
          {target.last_run !== undefined && (
            <>
              <div className="lbl" style={{ marginTop: 14 }}>Last run</div>
              <LastRunView target={target} />
            </>)}
          {(target.fields || []).length > 0 && <><hr className="line" /><FieldRows target={target} agentKey={agentKey} /></>}
        </div>)}
    </section>
  )
}
