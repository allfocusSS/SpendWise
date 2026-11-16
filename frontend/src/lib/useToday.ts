import { useEffect, useState } from 'react'

import { msUntilNextDay, startOfDay } from './dates'

/**
 * Today (local midnight), kept current for a tab left open: it moves on at midnight, and when the
 * tab is shown or focused again, since timers don't run while a computer sleeps. Stays the same
 * object all day, so it is safe in renders and query keys.
 */
export function useToday(): Date {
  const [today, setToday] = useState(() => startOfDay(new Date()))

  useEffect(() => {
    const refresh = () => {
      const now = startOfDay(new Date())
      setToday((current) => (current.getTime() === now.getTime() ? current : now))
    }
    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      // A second past midnight; a timer that fires early just finds the same day and waits again.
      timer = setTimeout(() => {
        refresh()
        schedule()
      }, msUntilNextDay(new Date()) + 1000)
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') refresh()
    }

    schedule()
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', refresh)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', refresh)
    }
  }, [])

  return today
}
