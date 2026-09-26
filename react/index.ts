/* The agents page as React components on Tenon, shared by the agents
 * dashboard and the to-dos board's Agents view, so there is one hour track.
 *
 * Shipped as source, not built: each app's own Vite compiles it, and each app
 * has to hand it one React and one Tenon (`resolve.dedupe` in its Vite config,
 * `paths` in its tsconfig), since this folder has no node_modules of its own.
 * The stylesheet is imported here, so an app that imports the component gets
 * it in its own CSS output. */
import './agents.css'

export { AgentsApp } from './AgentsApp'
export type { AgentsAppProps } from './AgentsApp'
