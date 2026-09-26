import { createContext, useContext } from 'react'
import type { State } from './types'

/* What every component under App needs and none of them should own.
 *
 * The page keeps no state beyond what is on screen: every change is a write
 * through the owning agent followed by a redraw, because the agent's own config
 * is the truth and a page holding its own copy of a schedule is a second place
 * for a schedule to be wrong. What is held here is the read, and the handful of
 * things that are about this browser rather than about an agent: which rows are
 * folded open, which hour the pointer is over, and which sheet is up.
 */
export interface Dash {
  state: State
  hover: number | null
  isOpen: (key: string) => boolean
  toggleOpen: (key: string) => void
  /* Hold the strip across a write and the redraw after it, then drop it. The
   * redraw is inside on purpose: the write itself returns quickly and it is the
   * read that follows that takes the time, so a strip ending at the write would
   * finish while the numbers on screen were still the old ones. */
  act: (fn: () => Promise<unknown>) => Promise<void>
  /* Starting a run and waiting for one are different waits, and this is the
   * first. The agent forks the run and answers straight away, so there is no
   * point holding a strip until the run finishes. */
  kick: (body: unknown) => Promise<void>
  run: (body: unknown) => Promise<unknown>
  syncHours: (x: number) => void
  openDetail: (agentKey: string, targetId: string, status?: string) => void
  openLog: (agentKey: string) => void
  /* Targets taken off this page, by rowKey. Kept in this browser only; the agent
   * is not told, and a hidden target keeps running. */
  isHidden: (key: string) => boolean
  setHidden: (key: string, hidden: boolean) => void
  /* What a target's last run built, opened from the "built last night" tag. */
  openBuilt: (agentKey: string, targetId: string) => void
  /* The order he last dragged agents and targets into, kept in this browser
   * only — the same reasoning as `hidden`. `orderAgents` and `orderTargets`
   * apply a saved order to a list, putting anything not yet in it at its
   * current place so a new agent or target still appears. `moveAgent` and
   * `moveTarget` (the latter scoped to one agent, since two agents can each
   * have their own row order) write a drag's result back. */
  orderAgents: <T,>(keyed: T[], keyOf: (t: T) => string) => T[]
  orderTargets: <T,>(agentKey: string, keyed: T[], keyOf: (t: T) => string) => T[]
  moveAgent: (key: string, before: string | null, allKeys: string[]) => void
  moveTarget: (agentKey: string, id: string, before: string | null, allIds: string[]) => void
}

export const DashContext = createContext<Dash | null>(null)

export function useDash(): Dash {
  const d = useContext(DashContext)
  if (!d) throw new Error('useDash outside <App>')
  return d
}
