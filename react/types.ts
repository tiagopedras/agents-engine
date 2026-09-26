/* The shape of /state.json lives in PACKAGES/agents-engine, so this page and any
 * other app reading an agent share one copy. CONTRACT.md at the root of the
 * repo is the authority; an agent may send more than is listed there and the
 * page ignores it. What is left here is about this page and nothing else. */

export type {
  Action, Agent, Boundary, Count, DetailCard, DetailGroup, Estimate, Field,
  LastRun, Load, Located, RunRow, State, StripCell, Target, Tone,
} from '../index.js'

export type View = 'cards' | 'list'
