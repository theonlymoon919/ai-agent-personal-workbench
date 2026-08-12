import { startTransition, useCallback, useEffect, useRef, useState } from 'react'
import { api, websocketUrl } from '../api.js'

export function useDashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState(null)
  const reconnectTimer = useRef(null)

  const reload = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try {
      const next = await api.dashboard()
      startTransition(() => {
        setData(next)
        setError('')
      })
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  useEffect(() => {
    let socket
    let closed = false

    const connect = () => {
      socket = new WebSocket(websocketUrl())
      socket.addEventListener('open', () => reload({ quiet: true }))
      socket.addEventListener('message', (event) => {
        const message = JSON.parse(event.data)
        if (message.type === 'refresh' || message.type === 'workspace.event') reload({ quiet: true })
        if (message.type === 'workspace.event' && message.event === 'agent_job.completed') {
          setNotice({ id: `${message.event}-${Date.now()}`, message: 'AI Agent 已完成处理，工作台内容已更新' })
          window.PersonalWorkbenchAndroid?.showNotification?.('AI Agent 已完成处理', '打开 AI Agent 个人工作台查看新结果')
        }
        if (message.type === 'workspace.event' && message.event === 'agent_job.failed') {
          setNotice({ id: `${message.event}-${Date.now()}`, message: 'AI Agent 处理遇到问题，请打开工作台查看状态', tone: 'error' })
          window.PersonalWorkbenchAndroid?.showNotification?.('AI Agent 处理遇到问题', '打开 AI Agent 个人工作台查看状态')
        }
      })
      socket.addEventListener('close', () => {
        if (!closed) reconnectTimer.current = window.setTimeout(connect, 1800)
      })
    }

    connect()
    return () => {
      closed = true
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
      socket?.close()
    }
  }, [reload])

  return { data, error, loading, reload, notice }
}
