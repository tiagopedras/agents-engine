import type { Agent, DetailCard, Estimate, Load, Located, State, Target } from './index'

export function hh(h: number | string): string
export function keyOf(a?: Agent): string
export function rowKey(agentKey: string, targetId: string): string
export function allTargets(s: State | null): Located[]
export function byName(targets?: Target[]): Target[]

export function loadByHour(s: State): Load
export function hourRanges(hours?: number[]): { from: number; to: number }[]
export function rangeText(hours?: number[]): string
export function nextStart(armed: Target[], now: number): string

export type AutoTone = 'plan' | 'bad' | 'off' | 'ok'
export interface Auto { tone: AutoTone; head: string; text: string; kv?: boolean }
export function autonomy(agent: Agent, now: number): Auto
export function jobLine(agent: Agent): { cls: string; text: string }

export function runLine(run: Target['last_run']): { text: string; empty?: boolean } | null
export function builtLastRun(run: Target['last_run']): number
export function builtLastNight(run: Target['last_run'], now?: number): number | null

export const STATUS: Record<string, { label: string; tone: 'good' | 'warn' | null }>
export const STATUSES: string[]
export function statusOf(c?: { status?: string } | null): string | null
export function cardLabel(c: DetailCard): string
export function estimateText(e?: Estimate): string
