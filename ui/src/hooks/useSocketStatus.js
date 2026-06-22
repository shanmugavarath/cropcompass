import { useState, useEffect } from 'react'
import { getSocket } from '../api/socket'

/**
 * Tracks the live WebSocket connection state.
 *
 * - 'idle'         — socket not yet opened (no message sent yet)
 * - 'connected'    — socket is open
 * - 'disconnected' — socket closed unexpectedly after a prior connection
 *
 * The socket is created lazily on the first `sendMessage` call, so we only
 * transition away from 'idle' once a chat has started.
 *
 * @returns {{ socketStatus: 'idle'|'connected'|'disconnected' }}
 */
export function useSocketStatus() {
  const [socketStatus, setSocketStatus] = useState('idle')

  useEffect(() => {
    const socket = getSocket()

    function onConnect()    { setSocketStatus('connected') }
    function onDisconnect() {
      // Only show "disconnected" if the farmer was actively using the socket
      setSocketStatus(prev => prev === 'idle' ? 'idle' : 'disconnected')
    }

    socket.on('connect',    onConnect)
    socket.on('disconnect', onDisconnect)

    return () => {
      socket.off('connect',    onConnect)
      socket.off('disconnect', onDisconnect)
    }
  }, [])

  return { socketStatus }
}
