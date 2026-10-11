import { useCallback, useEffect, useRef, useState } from 'react'
import { getErrorMessage } from '../api/client'

export default function useApi(fetcher) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const fetcherRef = useRef(fetcher)
  const requestId = useRef(0)

  useEffect(() => {
    fetcherRef.current = fetcher
  })

  const reload = useCallback(async ({ silent = false } = {}) => {
    const id = ++requestId.current
    if (!silent) setLoading(true)
    setError(null)
    try {
      const result = await fetcherRef.current()
      if (id === requestId.current) setData(result)
      return result
    } catch (err) {
      if (id === requestId.current) setError({ message: getErrorMessage(err), raw: err })
      return null
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  return { data, error, loading, reload, setData }
}
