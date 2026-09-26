import { useState } from 'react'
import { Button, Card, DragHandle, useReorder } from '@tiagopedras/tenon'
import type { ReorderItem } from '@tiagopedras/tenon'
import { useDash } from '../ctx'
import { autonomy, byName, jobLine, keyOf, relTime, rowKey, tilde } from '../lib'
import type { Agent, Load, State, Target } from '../types'
import { ActionButton } from './ActionButton'
import { NowMark, windowMarks } from './Ruler'
import { TargetRow } from './TargetRow'
import { CountLine } from './CountLine'

/* The one word over the list of targets, in both views. A target is a setting
 * sheet for the agent it sits under, and until this said so the rows were just
 * the rest of the panel. */
const TargetsHead = () => <h3 className="thead">Targets</h3>

/* Two folders, one agent. A copied repo brings its descriptor with it, so the
 * page draws two bands with the same name and the same id and no way to tell
 * which switch belongs to which. Each says where it was found and names the
 * other, which is also the answer to why there are two — and since a switch now
 * routes by key, turning one off leaves the other alone.
 */
function TwinLine({ agent }: { agent: Agent }) {
  if (!(agent.twin || []).length) return null
  return (
    <span className="bandsub bad" title={agent.root || ''}>
      Two folders claim this agent · this one is {tilde(agent.root)} ·
      the other is {agent.twin!.map(tilde).join(', ')}
    </span>
  )
}

/* The targets taken off this page, and the way back. One line under the targets
 * in both views, drawn only when something is hidden. */
function HiddenTargets({ agent, targets }: { agent: Agent; targets: Target[] }) {
  const { isHidden, setHidden } = useDash()
  const [open, setOpen] = useState(false)
  const agentKey = keyOf(agent)
  const hidden = targets.filter((t) => isHidden(rowKey(agentKey, t.id)))
  if (!hidden.length) return null
  return (
    <div className="hiddens">
      <button type="button" className="hlink" aria-expanded={open} onClick={() => setOpen(!open)}>
        Hidden · {hidden.length}
      </button>
      {open && (
        <ul>
          {hidden.map((t) => (
            <li key={t.id}>
              <span className="hname">{t.name}</span>
              <Button size="sm" onClick={() => setHidden(rowKey(agentKey, t.id), false)}>Show</Button>
            </li>))}
        </ul>)}
    </div>
  )
}

/* Where this agent is on disk and the one document that says what it is, as
 * the last line of every card and every panel.
 *
 * The links are `file://`, so they open the folder and the README straight
 * from the page. Chrome refuses to follow a `file://` link out of an `http://`
 * page and does nothing at all when one is clicked; Safari follows it. He
 * asked for them written this way knowing that.
 */
function WhereLine({ agent }: { agent: Agent }) {
  const root = agent.root || ''
  if (!root) return null
  const href = (p: string) => 'file://' + p.split('/').map(encodeURIComponent).join('/')
  return (
    <p className="clast where">
      <a href={href(root)}>{tilde(root)}</a>
      {agent.missing && ' · this folder is not there'}
    </p>
  )
}

/* Whether this agent does anything without being asked, drawn the same in both
 * views and written once.
 *
 * It carries everything that is true of the agent rather than of one of its
 * targets: whether launchd is holding the wake, what it does unasked and when,
 * what the last run did, and the buttons that override all of it. It sits under
 * the targets in both views, because it is the one answer for all of them at
 * once and a summary read before the thing it summarises has nothing to be read
 * against.
 */
function StatusBand({ agent, now, sub }: { agent: Agent; now: number; sub?: string }) {
  const { openLog } = useDash()
  const auto = autonomy(agent, now)
  const job = jobLine(agent)
  // The launchd line only when launchd is the problem. `autonomy` already says
  // whether this thing runs unasked, which is the same fact read the other way
  // round. What it does not say is the remedy, so the line stays for the two
  // states that have one.
  const trouble = agent.job && !agent.job.loaded ? job.text : ''
  const text = sub != null ? sub : [trouble, agent.summary].filter(Boolean).join(' · ')
  // The newest run any of its targets reported, in both views: the band reads
  // the same whichever one is showing, and the panel rows only print their own.
  const last = (agent.targets || []).map((t) => t.last_run).filter((r): r is NonNullable<typeof r> => !!r)
    .sort((a, b) => String(b.when || '').localeCompare(String(a.when || '')))[0]
  // The log opens in the sheet the target numbers already use, rather than
  // folding open inside the panel. It is the longest thing an agent has to say
  // and the least often wanted, and unfolding it in place pushed every agent
  // under it off the screen.
  const hasLog = (agent.log || []).length > 0
  const actions = agent.actions || []
  return (
    <div className={'cauto ' + auto.tone}>
      {text && <p className={'csub ' + (agent.tone || job.cls)}>{text}</p>}
      <p className={'aline' + (auto.kv ? ' kv' : '')}>
        <span className="ahead">{auto.head}</span>
        <span className="atext">{auto.text}</span>
      </p>
      {last && (
        <p className="aline kv">
          <span className="ahead">Last run</span>
          <span className="atext" title={last.when}>{[relTime(last.when), last.skipped || last.meta].filter(Boolean).join(' · ')}</span>
        </p>)}
      {(actions.length > 0 || hasLog) && (
        <div className="cacts">
          {actions.map((a) => <ActionButton key={a.id} action={a} agentKey={keyOf(agent)} />)}
          {hasLog && (
            <Button size="sm" aria-haspopup="dialog" onClick={() => openLog(keyOf(agent))}>
              Log{agent.running ? ' · a run is going' : ''}
            </Button>)}
        </div>)}
    </div>
  )
}

/* Just the buttons a status band would carry — Dry run, Run now, the log —
 * with none of the prose around them. The list panel's info column has no room
 * for the "on for N of M" / next run / last run text without crowding the
 * targets beside it, so it gets this instead and the fuller StatusBand stays
 * for the card view, where that text is the point. */
function AgentActions({ agent }: { agent: Agent }) {
  const { openLog } = useDash()
  const hasLog = (agent.log || []).length > 0
  const actions = agent.actions || []
  if (!actions.length && !hasLog) return null
  return (
    <div className="cacts pacts">
      {actions.map((a) => <ActionButton key={a.id} action={a} agentKey={keyOf(agent)} size="sm" />)}
      {hasLog && (
        <Button size="sm" aria-haspopup="dialog" onClick={() => openLog(keyOf(agent))}>
          Log{agent.running ? ' · a run is going' : ''}
        </Button>)}
    </div>
  )
}

/* The two words on a reference card, and the one place they are written.
 * Both views say it, and a built agent reading "not built yet" is the exact
 * thing this field was added to stop. */
const refSub = (agent: Agent) => (agent.kind === 'built' ? 'Built · not scheduled' : 'Planned · not built yet')

/* The same state read the other way round.
 *
 * The list puts every agent on one scale because the question it answers is
 * about the night as a whole — what is on, and does anything collide. That
 * scale is also what makes it a poor place to ask what any one of these things
 * actually is: the name gets a line, the description gets none, and an agent
 * with nothing scheduled is twenty-four empty blocks and a shrug.
 *
 * So a card drops the track entirely and spends the room on the four things a
 * track cannot say: what this is, whether it runs without being asked, what it
 * is holding, and what it did last. It is also the only view a reference agent
 * can be honest in, since it has no hours to draw at all.
 */
function AgentCard({ agent, now, drag }: { agent: Agent; now: number; drag: ReorderItem }) {
  const { isHidden, orderTargets, moveTarget } = useDash()
  const agentKey = keyOf(agent)
  const all = orderTargets(agentKey, byName(agent.targets), (t) => t.id)
  const targets = all.filter((t) => !isHidden(rowKey(agentKey, t.id)))
  const ids = targets.map((t) => t.id)
  const { item, listProps } = useReorder({ keys: ids, onMove: (id, before) => moveTarget(agentKey, id, before, ids) })
  const heading = (
    <div className="chead">
      <DragHandle {...drag.handleProps} />
      <h2 className="ctitle">{agent.name}</h2>
      {agent.blurb && <p className="cblurb">{agent.blurb}</p>}
    </div>
  )
  const cardProps = { className: 'acard', ...drag.itemProps }

  if (agent.reference) {
    return (
      <Card as="article" {...cardProps} className={cardProps.className + ' planned'}>
        {heading}
        <StatusBand agent={agent} now={0} sub={refSub(agent)} />
      </Card>
    )
  }

  // The name says what this is and the blurb says what it does, so they belong
  // together and nothing goes between them. Then the targets, which is the body
  // of the card and what it is opened to look at. The band is last: everything
  // in it is one answer, and that answer is about the card as a whole, so it
  // reads after the thing it is about.
  return (
    <Card as="article" {...cardProps}>
      {heading}
      {targets.length ? (
        <>
          <TargetsHead />
          <ul className="clines" {...listProps}>
            {targets.map((t) => <CountLine key={t.id} target={t} agent={agent} drag={item(t.id)} />)}
          </ul>
        </>
      ) : !all.length && <p className="empty">This agent has no targets yet.</p>}
      <HiddenTargets agent={agent} targets={all} />
      <StatusBand agent={agent} now={now} />
      <TwinLine agent={agent} />
    </Card>
  )
}

function AgentPanel({ agent, load, state, marks, nowLine, drag }: {
  agent: Agent
  load: Load
  state: State
  marks: React.ReactNode[]
  nowLine: React.ReactNode
  drag: ReorderItem
}) {
  const { isHidden, orderTargets, moveTarget } = useDash()
  const now = state.hour
  const cardProps = { className: 'panel', ...drag.itemProps }
  const agentKey = keyOf(agent)
  const all = orderTargets(agentKey, byName(agent.targets), (t) => t.id)
  const targets = all.filter((t) => !isHidden(rowKey(agentKey, t.id)))
  const ids = targets.map((t) => t.id)
  const { item, listProps } = useReorder({ keys: ids, onMove: (id, before) => moveTarget(agentKey, id, before, ids) })
  // No hours to draw and nothing to switch, so it gets a band and a line. It
  // still appears here rather than only in the cards view: the question this
  // page is opened with is what agents there are, and one that exists on paper
  // is part of that answer wherever you are standing.
  if (agent.reference) {
    return (
      <Card as="section" {...cardProps} className={cardProps.className + ' planned'}>
        <div className="band"><div className="bandtitle">
          <DragHandle {...drag.handleProps} />
          <span className="bandname">{agent.name}</span>
          {agent.blurb && <p className="cblurb">{agent.blurb}</p>}
        </div></div>
        <StatusBand agent={agent} now={0} sub={refSub(agent)} />
        <WhereLine agent={agent} />
      </Card>
    )
  }
  if (agent.broken) {
    return (
      <Card as="section" {...cardProps} className={cardProps.className + ' broken'}>
        <div className="band"><div className="bandtitle">
          <DragHandle {...drag.handleProps} />
          <span className="bandname">{agent.name}</span>
          <p className="cblurb">
            Its <code>state</code> command did not return usable JSON, so there is nothing to draw. {tilde(agent.root)}
          </p>
        </div></div>
        <StatusBand agent={agent} now={now} sub={'Not answering · ' + agent.broken} />
        <WhereLine agent={agent} />
      </Card>
    )
  }

  // Read top to bottom: what this agent is, the targets it holds, the one
  // answer that covers all of them, and where it lives on disk. The log is a
  // button in that answer rather than a fold at the foot of the panel: it is
  // the longest thing here and the least often wanted.
  return (
    <Card as="section" {...cardProps}>
      <div className="pinfo">
        <div className="band">
          <div className="bandtitle">
            <DragHandle {...drag.handleProps} />
            <span className="bandname">{agent.name}</span>
            {agent.blurb && <p className="cblurb">{agent.blurb}</p>}
            <TwinLine agent={agent} />
          </div>
        </div>
        <WhereLine agent={agent} />
      </div>

      <div className="ptargets">
        {targets.length > 0 && (
          <div className="ptargethead">
            <TargetsHead />
            <AgentActions agent={agent} />
          </div>
        )}
        <div className={'rows' + (marks.length ? ' marked' : '')} {...listProps}>
          {targets.length
            ? targets.map((t) => (
              <TargetRow key={t.id} target={t} agent={agent} load={load} now={now} drag={item(t.id)} />))
            : !all.length && <section className="trow"><p className="empty">This agent has no targets yet.</p></section>}
          {marks}{nowLine}
        </div>

        <HiddenTargets agent={agent} targets={all} />
      </div>
    </Card>
  )
}

/* Every agent, in whichever reading is showing. The order between agents is
 * one saved list shared by both views — a drag in the cards view holds when
 * you flip to list, the same promise `byName` inside each panel already keeps
 * for targets. */
export function Agents({ state, load, view }: { state: State; load: Load; view: 'cards' | 'list' }) {
  const { orderAgents, moveAgent } = useDash()
  const agents = orderAgents(state.agents || [], keyOf)
  const keys = agents.map(keyOf)
  const { item, listProps } = useReorder({
    keys, onMove: (key, before) => moveAgent(key, before, keys), axis: view === 'cards' ? 'x' : 'y',
  })
  // Worked out once and drawn into every panel. The boundaries are a fact about
  // the account, so the same marks fall in the same columns on all of them.
  const marks = view === 'list' ? windowMarks(state) : []
  const nowLine = view === 'list' ? <NowMark state={state} /> : null

  return (
    <div id="agents" className={view === 'cards' ? 'cards' : ''} {...listProps}>
      {agents.length
        ? agents.map((a) => (view === 'cards'
          ? <AgentCard key={keyOf(a)} agent={a} now={state.hour} drag={item(keyOf(a))} />
          : <AgentPanel key={keyOf(a)} agent={a} load={load} state={state} marks={marks} nowLine={nowLine}
              drag={item(keyOf(a))} />))
        : (
          <Card as="section" className="panel">
            <div className="rows"><section className="trow"><p className="empty">
              No agents found. An agent is any folder under ~/Code with an <code>agent.json</code> in it — see CONTRACT.md.
            </p></section></div>
          </Card>)}
    </div>
  )
}
