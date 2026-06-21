import { useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useChat } from '../hooks/useChat'
import MessageBubble from './MessageBubble'
import InputBar from './InputBar'

export default function ChatWindow({ farmerId }) {
  const { messages, sendMessage, pending, streaming, status } = useChat(farmerId)
  const bottomRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  function handleNewChat() {
    localStorage.removeItem('farmer_id')
    navigate('/onboarding')
  }

  return (
    <div className="chat-layout">
      <header className="chat-header">
        <h1>CropCompass</h1>
        <button
          className="btn-new-chat"
          onClick={handleNewChat}
          aria-label="Start a new chat and return to onboarding"
        >
          + New Chat
        </button>
      </header>

      <main
        className="chat-window"
        role="log"
        aria-label="Chat messages"
        aria-live="polite"
      >
        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {pending && !streaming && (
          <div className="message-row message-row--assistant">
            <div className="message-bubble message-bubble--assistant">
              {status ? (
                <p className="agent-status" aria-live="polite">{status}</p>
              ) : (
                <div className="typing-indicator" aria-label="Typing…">
                  <span /><span /><span />
                </div>
              )}
            </div>
          </div>
        )}
        {streaming && status && (
          <p className="agent-status agent-status--inline" aria-live="polite">{status}</p>
        )}

        <div ref={bottomRef} aria-hidden="true" />
      </main>

      <InputBar onSend={sendMessage} disabled={pending} />
    </div>
  )
}
