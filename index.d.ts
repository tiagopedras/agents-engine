/* The shape of what the agents dashboard server hands back. The authority is
 * CONTRACT.md in agents-dashboard, under `state`; an agent may send more than
 * is listed here. This is the only copy: the dashboard's own page reads its
 * types from here too. */

export type Tone = 'good' | 'warn' | 'bad'

export interface Count {
  n: number | string
  l: string
  kind?: 'total' | 'good' | 'warn'
  status?: string
  opens?: boolean
  title?: string
}

export interface RunRow { tone?: Tone; label?: string; text: string; tag?: string }

export interface LastRun {
  when?: string
  meta?: string
  skipped?: string
  rows?: RunRow[]
}

export interface Field {
  key: string
  type?: 'lines' | 'number' | 'text'
  label: string
  value: unknown
  rows?: number
  min?: number
  max?: number
  step?: number
  wide?: boolean
  headline?: string
  headline_tone?: Tone
}

export interface Action {
  id: string
  label: string
  primary?: boolean
  slow?: boolean
  title?: string
}

export interface Estimate { unit?: string; low?: number; high?: number; n?: number }

export interface DetailCard {
  text: string
  status?: string
  state?: string
  tone?: Tone
  tags?: string[]
  index?: string | number
  why?: string
  done?: boolean
  estimate?: Estimate
}

export interface DetailGroup { name: string; cards: DetailCard[] }

export interface Target {
  id: string
  name: string
  subtitle?: string
  subtitle_title?: string
  note?: string
  on?: boolean
  switchable?: boolean
  hours?: number[]
  hours_editable?: boolean
  counts?: Count[]
  /* undefined: this target has no runs to report. null: it has had none yet. */
  last_run?: LastRun | null
  chips?: { label: string; items: string[] }
  fields?: Field[]
  problems?: string[]
  actions?: Action[]
  detail?: { title?: string; groups?: DetailGroup[] }
}

export interface Agent {
  key?: string
  id: string
  name: string
  blurb?: string
  summary?: string
  tone?: string
  root?: string
  doc?: string
  /* A reference agent whose folder is not there. */
  missing?: boolean
  /* The other folders claiming the same id. */
  twin?: string[]
  /* From references.json: no commands, nothing to run or schedule. */
  reference?: boolean
  kind?: string
  cadence?: string
  started_by?: string
  broken?: string
  running?: boolean
  job?: { loaded?: boolean; installed?: boolean }
  hours_preferred?: number[]
  targets?: Target[]
  actions?: Action[]
  log?: string[]
}

export interface AgentView { now: string; hour: number; agent: Agent }

export interface StripCell { cls?: string; k: string; v: string; w?: string }

export interface Boundary { at: string; why?: string }

export interface State {
  now?: string | number
  hour: number
  agents?: Agent[]
  strip?: StripCell[]
  boundaries?: Boundary[]
}

export interface Ok { ok: true; [k: string]: unknown }

export interface AgentsClient {
  getAgent(key: string): Promise<AgentView>
  getAll(): Promise<State>
  setHours(agent: string, target: string, hours: number[]): Promise<Ok>
  setOn(agent: string, target: string, on: boolean): Promise<Ok>
  setField(agent: string, target: string, key: string, value: unknown): Promise<Ok>
  apply(agent: string, target: string, changes: Record<string, unknown>): Promise<Ok>
  run(agent: string, action: string, target?: string): Promise<Ok>
}

export const DEFAULT_BASE: string

export function createClient(options?: { base?: string; fetch?: typeof fetch }): AgentsClient
