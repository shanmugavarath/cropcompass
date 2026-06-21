import { getMockSocket } from './mock/server.js'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8001'

let _socket = null

// Wraps a native WebSocket in the same .on()/.off()/.emit() interface that
// useChat.js expects. Incoming frames are dispatched by data.type so that
// step-5.2's streaming handler can bind to 'token', 'phase', 'final', etc.
// Each frame is also echoed as 'response' so the current useChat.js keeps
// working until step 5.2 lands.
function createAdapter() {
  const ws = new WebSocket(`${WS_URL}/ws/chat`)
  const listeners = {}

  function dispatch(event, payload) {
    ;(listeners[event] ?? []).forEach(h => h(payload))
  }

  ws.onmessage = (evt) => {
    let data
    try { data = JSON.parse(evt.data) } catch { return }
    const type = data.type ?? 'response'
    dispatch(type, data)
    if (type !== 'response') dispatch('response', data)
  }

  ws.onerror = () => {
    dispatch('error', { type: 'error', message: 'WebSocket error' })
  }

  ws.onclose = () => {
    dispatch('disconnect', {})
  }

  return {
    on(event, handler) {
      ;(listeners[event] ??= []).push(handler)
    },
    off(event, handler) {
      if (listeners[event]) {
        listeners[event] = listeners[event].filter(h => h !== handler)
      }
    },
    emit(event, payload) {
      if (event === 'chat' && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(payload))
      }
    },
    disconnect() {
      ws.close()
    },
    get connected() {
      return ws.readyState === WebSocket.OPEN
    },
  }
}

export function getSocket() {
  if (_socket) return _socket
  _socket = import.meta.env.VITE_USE_MOCK === 'true'
    ? getMockSocket()
    : createAdapter()
  return _socket
}

export function resetSocket() {
  if (_socket?.disconnect) _socket.disconnect()
  _socket = null
}
