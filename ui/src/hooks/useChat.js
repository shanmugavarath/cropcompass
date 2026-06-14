import { useState, useEffect, useCallback } from 'react'
import { getSocket, resetSocket } from '../api/socket'

// Initial greeting shown before the farmer sends their first message.
// lang_pref localisation happens in Task 4.3 once the profile API is wired.
const WELCOME_MESSAGE = {
  role: 'assistant',
  type: 'greeting',
  text: 'नमस्ते! मैं CropCompass हूँ — आपका कृषि सलाहकार।\nHello! I am CropCompass — your crop advisory assistant.\nअपनी फसल के बारे में कोई भी सवाल पूछें।',
  lang: 'hin_Deva',
}

export function useChat(farmerId) {
  const [messages, setMessages] = useState([WELCOME_MESSAGE])
  const [pending, setPending] = useState(false)

  useEffect(() => {
    // Connect socket and register response listener on mount
    const socket = getSocket()

    function onResponse(data) {
      setMessages(prev => [...prev, { role: 'assistant', data }])
      setPending(false)
    }

    socket.on('response', onResponse)

    // Clean up listener and disconnect on unmount
    return () => {
      socket.off('response', onResponse)
      resetSocket()
    }
  }, [])

  const sendMessage = useCallback(
    text => {
      // Optimistically append user bubble before the server responds
      setMessages(prev => [...prev, { role: 'user', text }])
      setPending(true)
      getSocket().emit('chat', { farmer_id: farmerId, message: text })
    },
    [farmerId],
  )

  return { messages, sendMessage, pending }
}
