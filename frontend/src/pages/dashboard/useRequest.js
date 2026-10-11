import { useCallback, useEffect, useRef, useState } from 'react'
import { getErrorMessage, isNotBuilt } from '../../api/client'

export default function useRequest(fetcher) {
  const [state, setState] = useState({ data: null, loading: true, error: '', notBuilt: false })
  const latest = useRef(0)

  const run = useCallback(async () => {
    const id = ++latest.current
    try {
      const data = await fetcher()
      if (id === latest.current) setState({ data, loading: false, error: '', notBuilt: false })
    } catch (error) {
      if (id === latest.current) {
        setState({ data: null, loading: false, error: getErrorMessage(error), notBuilt: isNotBuilt(error) })
      }
    }
  }, [fetcher])

  useEffect(() => {
    run()
    return () => {
      latest.current += 1
    }
  }, [run])

  const reload = useCallback(() => {
    setState((current) => ({ ...current, loading: true, error: '', notBuilt: false }))
    run()
  }, [run])

  return { ...state, reload }
}
