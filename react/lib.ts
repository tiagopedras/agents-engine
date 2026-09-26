/* The schedule arithmetic, the run lines and the status words live in
 * PACKAGES/agents-engine, so any app monitoring agents gets the same answers.
 * What is left here is about drawing this page. */

export {
  allTargets, autonomy, builtLastNight, builtLastRun, byName, cardLabel,
  estimateText, hh, jobLine, keyOf, loadByHour, rangeText, rowKey, runLine,
  STATUS, STATUSES, statusOf,
} from '../schedule.js'
export type { Auto, AutoTone } from '../schedule.js'

// `/Users/tiagopedras/Code/…` is the same eleven leading characters on every
// row, and they are the ones a narrow row truncates in favour of. The full
// path is still on the element's title.
export const tilde = (p?: string) => String(p || '').replace(/^\/Users\/[^/]+/, '~')

/* Where along the track an instant falls, as the `right` offset of a mark drawn
 * down the whole stack of rows.
 *
 * The track is twenty-four blocks with a gap between each, hung off the same
 * right edge in every row, so one calculation places a mark in every row at
 * once. It is the arithmetic `.rows::after` already uses for the lines down the
 * day. */
export function markRight(h: number, m: number) {
  return `calc(var(--rowpad) + var(--trackr) + ${(24 - h - m / 60).toFixed(4)} * var(--hw)`
    + ` + ${23 - h} * var(--hgap))`
}

/* A run's `when`, "2026-09-22 21:04", said the way a person would: "3 h ago",
 * "yesterday", "4 days ago". Past a week the date itself is quicker to read
 * than a count of days. The exact time goes on the element's title. */
export function relTime(when?: string, now = Date.now()) {
  const at = Date.parse(String(when || '').replace(' ', 'T'))
  if (Number.isNaN(at)) return when || ''
  const min = Math.round((now - at) / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const d = new Date(at), today = new Date(now)
  const days = Math.round((new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
    - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000)
  if (days === 0) return `${Math.round(min / 60)} h ago`
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

// The same run with its `when` said relatively, for the one-line helpers in
// agents-engine that print `when` as they find it.
export const relRun = <R extends { when?: string } | null | undefined>(run: R, now = Date.now()): R =>
  run ? { ...run, when: relTime(run.when, now) } : run
