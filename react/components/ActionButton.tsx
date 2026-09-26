import { useEffect, useRef, useState } from 'react'
import { Button, Spinner } from '@tiagopedras/tenon'
import { useDash } from '../ctx'
import type { Action } from '../types'

/* A button that starts something on an agent. `slow` ones — walking ~/Code for
 * repos, say — hold the button for the whole round trip, because there is
 * nothing detached about them and the answer is the point. The rest hold it for
 * a fixed second and a half: the agent forks the run and answers straight away,
 * and it is the redraw that follows that first shows the run as going. */
export function ActionButton({ action, agentKey, targetId, size = 'md' }: {
  action: Action
  agentKey: string
  targetId?: string
  size?: 'sm' | 'md'
}) {
  const { act, kick, run } = useDash()
  const [working, setWorking] = useState(false)
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])

  const click = async () => {
    const body = { agent: agentKey, action: action.id, target: targetId || null }
    setWorking(true)
    try {
      if (action.slow) await act(() => run(body))
      else await kick(body)
    } finally {
      if (alive.current) setWorking(false)
    }
  }

  return (
    <Button
      variant={action.primary ? 'primary' : 'secondary'}
      size={size}
      title={action.title || ''}
      disabled={working}
      endIcon={working ? <Spinner size="sm" label="Working" /> : undefined}
      onClick={click}
    >
      {action.label}
    </Button>
  )
}
