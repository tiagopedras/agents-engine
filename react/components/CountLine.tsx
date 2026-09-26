import { useDash } from '../ctx'
import { builtLastNight, keyOf, rangeText, STATUS } from '../lib'
import type { Agent, Target } from '../types'
import { DragHandle } from '@tiagopedras/tenon'
import type { ReorderItem } from '@tiagopedras/tenon'
import { Bell, HideButton, TargetSwitch } from './TargetRow'

/* One line per target on a card, in two rows: the switch, the name and its bell,
 * then under the name its window in words and the numbers it carries. The window
 * is the hour track's content without its geometry, which is all a card needs,
 * since nothing here is being compared against another agent's. */
export function CountLine({ target: t, agent, drag }: { target: Target; agent: Agent; drag?: ReorderItem }) {
  const { openDetail, openBuilt } = useDash()
  const agentKey = keyOf(agent)
  const when = (t.hours || []).length ? rangeText(t.hours) : 'no schedule'

  // The one number a line can carry without becoming a row: how much this
  // target has that can be built now. It opens the same sheet narrowed to the
  // same status the row's number does, so a line is a way into a repo here
  // rather than only a label for one.
  //
  // A target that counted nothing and a target that was never read are not the
  // same fact, and drawing the second as a blank makes it the quieter of the
  // two when it is the one with something wrong. So an agent that sent no
  // counts at all says so, with its own first problem as the reason. Tested on
  // the whole of `counts` rather than on the tagged one: an agent that counts
  // things and tags none of them has been read.
  const build = (t.counts || []).length
    ? (t.counts || []).filter((c) => c.kind === 'good').map((c, i) => {
      const inner = <><span className="n">{c.n}</span><span className="l">{c.l}</span></>
      const status = c.status && STATUS[c.status] ? c.status : undefined
      const opens = c.opens && !(status && !Number(c.n))
      return opens
        ? <button key={i} type="button" className="count" aria-haspopup="dialog" title={c.title || ''}
            onClick={() => openDetail(agentKey, t.id, status)}>{inner}</button>
        : <span key={i} className="count">{inner}</span>
    })
    : <span className="count none" title={(t.problems || [])[0] || 'This agent reported no counts for this target.'}>
        <span className="l">nothing read</span>
      </span>

  // What the last run built, when it was last night's. Pressing it lists what.
  // Nothing built has nothing to list, so a zero is a label and not a button.
  const built = builtLastNight(t.last_run)
  const inner = <><span className="n">{built}</span><span className="l">built last night</span></>
  const builtTag = built === null ? null : built > 0
    ? <button type="button" className="count" aria-haspopup="dialog"
        onClick={() => openBuilt(agentKey, t.id)}>{inner}</button>
    : <span className="count">{inner}</span>

  return (
    <li className={'cline ' + (t.on ? 'on' : 'off')} {...drag?.itemProps}>
      {drag && <DragHandle {...drag.handleProps} />}
      <TargetSwitch target={t} agentKey={agentKey} />
      <div className="cid">
        <div className="cnamerow">
          <span className="cname" title={t.subtitle_title || t.subtitle || ''}>{t.name}</span>
          <Bell problems={t.problems} name={t.name} />
        </div>
        <div className="cmeta">
          <span className="cwhen">{when}</span>
          {build}
          {builtTag}
        </div>
      </div>
      <HideButton target={t} agentKey={agentKey} />
    </li>
  )
}
