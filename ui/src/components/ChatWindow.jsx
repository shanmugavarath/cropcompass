import { useRef, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useChat } from '../hooks/useChat'
import { useSpeech } from '../hooks/useSpeech'
import { useSocketStatus } from '../hooks/useSocketStatus'
import MessageBubble from './MessageBubble'
import InputBar from './InputBar'
import STRINGS from '../localization/index'

export default function ChatWindow({ farmerId, langPref }) {
  const { messages, sendMessage, pending, streaming, status } = useChat(farmerId, langPref)
  const { speak, stop: stopSpeech } = useSpeech()
  const { socketStatus } = useSocketStatus()
  const [autoRead, setAutoRead] = useState(false)
  // Hide suggestion chips once the farmer sends their first message
  const [suggestionsVisible, setSuggestionsVisible] = useState(true)
  const bottomRef       = useRef(null)
  const navigate        = useNavigate()
  const prevMsgCount    = useRef(0)
  const strings         = STRINGS[langPref] ?? STRINGS.eng_Latn
  const autoReadLabel   = strings.autoReadLabel  ?? 'Auto-read answers'
  const suggestions     = strings.suggestions    ?? []
  const reconnectLabel  = 'Reconnecting…'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  // Auto-read: speak new final agent messages when the toggle is on
  useEffect(() => {
    if (!autoRead) return
    const count = messages.length
    if (count > prevMsgCount.current) {
      const latest = messages[count - 1]
      if (latest && latest.role !== 'user' && latest.type !== 'streaming') {
        const text = latest.data?.text ?? latest.text ?? ''
        const lang = latest.data?.lang ?? latest.lang ?? langPref
        if (text) speak(text, lang)
      }
    }
    prevMsgCount.current = count
  }, [messages, autoRead, speak, langPref])

  function handleNewChat() {
    stopSpeech()
    localStorage.removeItem('farmer_id')
    localStorage.removeItem('lang_pref')
    navigate('/onboarding')
  }

  function handleSuggestion(text) {
    setSuggestionsVisible(false)
    sendMessage(text)
  }

  // Also hide chips once the farmer types and sends manually
  function handleSend(text) {
    setSuggestionsVisible(false)
    sendMessage(text)
  }

  // Only show chips before any user message has been sent
  const hasUserMessage = messages.some(m => m.role === 'user')
  const showChips = suggestionsVisible && !hasUserMessage && suggestions.length > 0

  return (
    <div className="chat-layout">
      {/* Connection-status banner — only shown after first disconnect */}
      {socketStatus === 'disconnected' && (
        <div className="connection-banner" role="status" aria-live="polite">
          <span className="connection-banner__dot" aria-hidden="true" />
          {reconnectLabel}
        </div>
      )}

      <header className="chat-header">
        <h1>CropCompass</h1>
        <div className="chat-header__actions">
          <label className="auto-read-toggle" title={autoReadLabel}>
            <input
              type="checkbox"
              checked={autoRead}
              onChange={e => {
                setAutoRead(e.target.checked)
                if (!e.target.checked) stopSpeech()
              }}
              aria-label={autoReadLabel}
            />
            <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
            </svg>
            <span className="sr-only">{autoReadLabel}</span>
          </label>
          <button
            className="btn-new-chat"
            onClick={handleNewChat}
            aria-label="Start a new chat and return to onboarding"
          >
            + New Chat
          </button>
        </div>
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

        {/* Suggested-question chips — shown only before first user message */}
        {showChips && (
          <div className="suggestion-chips" role="group" aria-label="Suggested questions">
            {suggestions.map((s, i) => (
              <button
                key={i}
                className="suggestion-chip"
                onClick={() => handleSuggestion(s)}
                disabled={pending}
              >
                {s}
              </button>
            ))}
          </div>
        )}

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

      <InputBar onSend={handleSend} disabled={pending} langPref={langPref} />
    </div>
  )
}
