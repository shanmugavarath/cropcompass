import { useState, useRef } from 'react'

export default function InputBar({ onSend, disabled }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

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
