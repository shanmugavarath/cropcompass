import { useState, useRef, useEffect } from 'react'
import { useSpeechInput } from '../hooks/useSpeechInput'
import STRINGS from '../localization/index'

export default function InputBar({ onSend, disabled, langPref = 'eng_Latn' }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)
  const { supported, listening, transcript, start, stop } = useSpeechInput(langPref)

  // Pipe incoming transcript into the text box so the farmer can review before sending
  useEffect(() => {
    if (!transcript) return
    const capped = transcript.slice(0, 500)
    setText(capped)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [transcript])

  function submit() {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function onInput(e) {
    setText(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${e.target.scrollHeight}px`
  }

  function toggleMic() {
    if (listening) stop()
    else start()
  }

  const strings  = STRINGS[langPref] ?? STRINGS.eng_Latn
  const micLabel = strings.micLabel ?? 'Speak your question'

  return (
    <div className="input-bar">
      <label htmlFor="chat-input" className="sr-only">
        Type your question
      </label>
      <textarea
        id="chat-input"
        ref={textareaRef}
        value={text}
        onChange={onInput}
        onKeyDown={onKeyDown}
        placeholder="अपना सवाल यहाँ लिखें… / Type your question…"
        disabled={disabled}
        rows={1}
        aria-label="Type your question"
        maxLength={500}
      />

      {/* Mic button — only rendered when the browser supports SpeechRecognition */}
      {supported && (
        <button
          className={`mic-btn${listening ? ' mic-btn--active' : ''}`}
          onClick={toggleMic}
          disabled={disabled}
          aria-label={micLabel}
          aria-pressed={listening}
          type="button"
          title={micLabel}
        >
          {listening && <span className="mic-dot" aria-hidden="true" />}
          <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18" aria-hidden="true">
            <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.93V20H9v2h6v-2h-2v-2.07A7 7 0 0 0 19 11h-2z" />
          </svg>
        </button>
      )}

      <button
        className="send-btn"
        onClick={submit}
        disabled={disabled || !text.trim()}
        aria-label="Send message"
      >
        ➤
      </button>
    </div>
  )
}
