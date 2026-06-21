import { io } from 'socket.io-client'
import { getMockSocket } from './mock/server.js'

let _socket = null

export function getSocket() {
  if (_socket) return _socket

  if (import.meta.env.VITE_USE_MOCK === 'true') {
    _socket = getMockSocket()
  } else {
    _socket = io(import.meta.env.VITE_API_URL, { transports: ['websocket'] })
  }

  return _socket
}

// Call when the app needs a fresh connection (e.g. after farmer_id changes)
export function resetSocket() {
  if (_socket && typeof _socket.disconnect === 'function') {
    _socket.disconnect()
  }
  _socket = null
}
