import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { applySavedOrder, reorderKeys } from '@tiagopedras/tenon'
import { getJSON, postJSON, setBase } from './api'
import { DashContext } from './ctx'
import type { Dash } from './ctx'
import { loadByHour, tilde } from './lib'
import type { State, View } from './types'
import { Agents } from './components/AgentView'
import { Boot, Header, ProgressBar, Problem, Strip } from './components/Chrome'
import { Ruler } from './components/Ruler'
import { Sheet } from './components/Sheet'
import type { SheetKind } from './components/Sheet'

/* The agents page, as one component. The agents dashboard is this and a
 * stylesheet for the body; the to-dos board mounts it as its Agents view.
 *
 * `base` is where the four routes are answered, `title` is the heading, and
 * `storagePrefix` keeps this browser's preferences for one app apart from
 * another's on the same origin. `embedded` is for a page that already has a
 * header of its own: the first-load cover stays inside the component rather
 * than covering the window.
 *
 * It draws whatever /state.json says and posts back the things an agent has
 * declared editable — a target's switch, its schedule, and whatever fields it
 * listed. Nothing here knows what an agent builds. Every label, every pill and
 * every field came out of the agent that owns it, which is why adding a third
 * agent needs no change here. CONTRACT.md at the root of the repo is the shape.
 *
 * A target is a row, not a card. The page is opened to answer one question —
 * what is going to run tonight, and does any of it land on top of anything
 * else — and that question is about a column of the day rather than about any
 * one repo. So every target draws its twenty-four hours on the same track at
 * the same width, hard against the right edge, one row under another. Two
 * things armed at 03:00 are then two blocks in the same column, and the overlap
 * is the shape of the page rather than something to be worked out by reading
 * six separate grids. Everything else a target has is behind the row's own
 * disclosure, because none of it is the question the page is opened for.
 */

const EMPTY: State = { hour: 0, agents: [] }
const message = (err: unknown) => (err instanceof Error ? err.message : String(err))

/* Remembered per browser, and the cards are what a first visit gets.
 *
 * localStorage rather than anything the helper writes: which of two readings he
 * last had open is about this browser and nothing else, and putting it through
 * the server would make a preference into a file with a schema. Wrapped because
 * a private window throws on the read rather than returning nothing, and a page
 * that will not draw at all because it could not remember a tab is a bad trade.
 */
function readView(prefix: string): View {
  try { if (localStorage.getItem(prefix + 'view') === 'list') return 'list' } catch { /* private window, or storage turned off */ }
  return 'cards'
}

// The targets taken off the page, remembered the same way and for the same
// reason as the view: it is about this browser, not about the agent.
function readHidden(prefix: string): Set<string> {
  try {
    const list = JSON.parse(localStorage.getItem(prefix + 'hidden') || '[]')
    if (Array.isArray(list)) return new Set(list.filter((x): x is string => typeof x === 'string'))
  } catch { /* private window, storage turned off, or a value that is not JSON */ }
  return new Set()
}

/* The order he last dragged agents into, and the order per agent he last
 * dragged its targets into. Both are about this browser, the same as `hidden`
 * and `view` above, and both fall back to empty rather than failing the page
 * when storage is unavailable or holds something that is not JSON. */
function readAgentOrder(prefix: string): string[] {
  try {
    const list = JSON.parse(localStorage.getItem(prefix + 'agentOrder') || '[]')
    if (Array.isArray(list)) return list.filter((x): x is string => typeof x === 'string')
  } catch { /* private window, storage turned off, or a value that is not JSON */ }
  return []
}
function readTargetOrder(prefix: string): Record<string, string[]> {
  try {
    const obj = JSON.parse(localStorage.getItem(prefix + 'targetOrder') || '{}')
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
      const out: Record<string, string[]> = {}
      for (const [k, v] of Object.entries(obj)) {
        if (Array.isArray(v)) out[k] = v.filter((x): x is string => typeof x === 'string')
      }
      return out
    }
  } catch { /* private window, storage turned off, or a value that is not JSON */ }
  return {}
}


export interface AgentsAppProps {
  base?: string
  title?: string
  storagePrefix?: string
  embedded?: boolean
}

export function AgentsApp({ base = '', title = 'Agents Dashboard', storagePrefix = '', embedded = false }: AgentsAppProps) {
  // Set during render rather than in an effect, so the first fetch below
  // already goes to the right place.
  setBase(base)
  const px = storagePrefix
  const [state, setState] = useState<State | null>(null)
  const [view, setView] = useState<View>(() => readView(px))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(0)
  const [booted, setBooted] = useState(false)
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const [hidden, setHiddenSet] = useState<Set<string>>(() => readHidden(px))
  const [agentOrder, setAgentOrder] = useState<string[]>(() => readAgentOrder(px))
  const [targetOrder, setTargetOrder] = useState<Record<string, string[]>>(() => readTargetOrder(px))
  const [hover, setHover] = useState<number | null>(null)
  const [sheet, setSheet] = useState<SheetKind | null>(null)
  const pending = useRef(0)
  const sheetUp = useRef(false)
  const hoursX = useRef(0)
  sheetUp.current = sheet !== null

  const hold = () => { pending.current += 1; setBusy(pending.current) }
  const release = () => { pending.current = Math.max(0, pending.current - 1); setBusy(pending.current) }

  /* A quiet refresh draws no strip. The twenty-second poll and the redraw at the
   * end of `act` are both quiet: the poll because a bar flashing every twenty
   * seconds on its own reads as something going wrong, and `act` because it is
   * already inside a strip of its own. */
  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) hold()
    try {
      setState(await getJSON<State>('/state.json'))
      setError(null)
    } catch (err) {
      setError('Cannot reach the helper — is it still running? ' + message(err))
    } finally {
      if (!quiet) release()
      setBooted(true)
    }
  }, [])

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    hold()
    try {
      await fn()
      await refresh(true)
    } catch (err) {
      setError('That did not go through — ' + message(err))
    } finally {
      release()
    }
  }, [refresh])

  const kick = useCallback(async (body: unknown) => {
    hold()
    try {
      await postJSON('/run', body)
    } catch (err) {
      setError('That did not go through — ' + message(err))
    }
    await new Promise((r) => setTimeout(r, 1500))
    await refresh(true)
    release()
  }, [refresh])

  // Slow on purpose. Nothing here changes on its own except during a run, and a
  // dashboard polling hard is a dashboard that shows up in the usage it reports.
  // It also stands down while a write of his is in flight, so a poll landing
  // then does not take the pulse off the block he just clicked before the write
  // it belongs to has come back, and while a sheet is open, so the list under
  // his finger does not change.
  useEffect(() => {
    void refresh()
    const timer = setInterval(() => {
      if (pending.current === 0 && !sheetUp.current) void refresh(true)
    }, 20000)
    return () => clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    document.body.classList.toggle('agents-modalopen', sheet !== null)
    return () => { document.body.classList.remove('agents-modalopen') }
  }, [sheet])

  /* On a phone every hour track scrolls sideways on its own (see "a phone" in
   * dash.css), and the columns only line up if they all sit at the same offset.
   * So a scroll on one is copied to the ruler and every row, and remembered,
   * since a redraw brings tracks back scrolled to zero. Copying the same value
   * back onto the track that fired changes nothing and fires nothing, so this
   * cannot loop. On a wider window nothing overflows and no track ever
   * scrolls. */
  const syncHours = useCallback((x: number) => {
    hoursX.current = x
    document.querySelectorAll<HTMLElement>('.agents-ui .hours').forEach((e) => { if (e.scrollLeft !== x) e.scrollLeft = x })
  }, [])
  useLayoutEffect(() => { syncHours(hoursX.current) })

  const pickView = (v: View) => {
    setView(v)
    try { localStorage.setItem(px + 'view', v) } catch { /* nothing to do about it */ }
  }

  const s = state || EMPTY
  const load = useMemo(() => loadByHour(s), [s])

  const dash: Dash = {
    state: s,
    hover,
    isOpen: (key) => open.has(key),
    toggleOpen: (key) => setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    }),
    isHidden: (key) => hidden.has(key),
    setHidden: (key, on) => {
      const next = new Set(hidden)
      if (on) next.add(key); else next.delete(key)
      setHiddenSet(next)
      try { localStorage.setItem(px + 'hidden', JSON.stringify([...next])) } catch { /* nothing to do about it */ }
    },
    act,
    kick,
    run: (body) => postJSON('/run', body),
    syncHours,
    openDetail: (agent, target, status) => setSheet({ kind: 'detail', agent, target, status }),
    openLog: (agent) => setSheet({ kind: 'log', agent }),
    openBuilt: (agent, target) => setSheet({ kind: 'built', agent, target }),
    orderAgents: (keyed, keyOf) => applySavedOrder(keyed, keyOf, agentOrder),
    orderTargets: (agentKey, keyed, keyOf) => applySavedOrder(keyed, keyOf, targetOrder[agentKey] || []),
    moveAgent: (key, before, allKeys) => {
      const next = reorderKeys(allKeys, key, before)
      setAgentOrder(next)
      try { localStorage.setItem(px + 'agentOrder', JSON.stringify(next)) } catch { /* nothing to do about it */ }
    },
    moveTarget: (agentKey, id, before, allIds) => {
      const next = { ...targetOrder, [agentKey]: reorderKeys(allIds, id, before) }
      setTargetOrder(next)
      try { localStorage.setItem(px + 'targetOrder', JSON.stringify(next)) } catch { /* nothing to do about it */ }
    },
  }

  // One hour, lit everywhere it appears: in the ruler and in every row under
  // it. Six rows of blank blocks read as an overlap only if the eye can hold
  // the column, and hovering one is how you check that the two blocks you think
  // are stacked really are.
  const onOver = (ev: React.MouseEvent) => {
    const cell = (ev.target as Element).closest<HTMLElement>('[data-h]')
    setHover(cell ? Number(cell.dataset.h) : null)
  }

  const agents = s.agents || []

  return (
    <DashContext.Provider value={dash}>
      <div className={'agents-ui agents-root' + (embedded ? ' embedded' : '')} onMouseOver={onOver}>
        <ProgressBar active={busy > 0} />
        <Boot done={booted} />
        <Header state={state} view={view} onView={pickView} title={title} />
        <Problem message={error} onDismiss={() => setError(null)} />
        <Strip state={state} />
        {state && view === 'list' && <Ruler state={s} load={load} />}
        {state && <Agents state={s} load={load} view={view} />}
        <Sheet sheet={sheet} state={s} onClose={() => setSheet(null)} />
        <footer className="foot">
          <span>
            {agents.length
              ? agents.map((a) => a.name + ' · ' + tilde(a.root || '')).join('  —  ')
              : '~/Code'}
          </span>
        </footer>
      </div>
    </DashContext.Provider>
  )
}
