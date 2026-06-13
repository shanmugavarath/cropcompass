import { useState, useEffect, useCallback } from 'react'
import { getSocket } from '../api/socket'

export function useChat(farmerId) {
  const [messages, setMessages] = useState([])
  const [pending, setPending] = useState(false)

  useEffect(() => {
    const socket = getSocket()

    function onResponse(data) {
      setMessages(prev => [...prev, { role: 'assistant', data }])
      setPending(false)
    }

    socket.on('response', onResponse)
    return () => {
      socket.off('response', onResponse)
    }
  }, [])

  const sendMessage = useCallback(
    text => {
      setMessages(prev => [...prev, { role: 'user', text }])
      setPending(true)
      getSocket().emit('chat', { farmer_id: farmerId, message: text })
    },
    [farmerId],
  )

  return { messages, sendMessage, pending }
}
