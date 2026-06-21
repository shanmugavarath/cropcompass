import { useState, useEffect, useCallback, useRef } from 'react'
import { getSocket, resetSocket } from '../api/socket'
import STRINGS from '../localization/index'

function buildWelcomeMessage(t, lang) {
  return {
    role: 'assistant',
    type: 'greeting',
    text: t.greeting,
    lang,
  }
}

function buildPhaseLabels(t) {
  return {
    gather:    t.phaseGather,
    generate:  t.phaseGenerate,
    verify:    t.phaseVerify,
    translate: t.phaseTranslate,
  }
}

function buildToolLabels(t) {
  return {
    get_farmer_profile:    t.toolGetProfile,
    fetch_latest_advisory: t.toolFetchAdvisory,
    query_knowledge_base:  t.toolQueryKb,
    translate_output:      t.toolTranslate,
  }
}

export function useChat(farmerId, langPref = 'eng_Latn') {
  const t = STRINGS[langPref] ?? STRINGS.eng_Latn
  const PHASE_LABELS = buildPhaseLabels(t)
  const TOOL_LABELS = buildToolLabels(t)

  const [messages, setMessages] = useState(() => [buildWelcomeMessage(t, langPref)])
  const [pending, setPending] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [status, setStatus] = useState(null)
  // Tracks whether a streaming bubble is currently in the messages array.
  // A ref (not state) avoids stale-closure issues inside the onToken callback.
  const streamingActiveRef = useRef(false)

  useEffect(() => {
    const socket = getSocket()

    function onPhase(event) {
      setStatus(PHASE_LABELS[event.data?.phase] ?? event.data?.phase ?? null)
    }

    function onToolCall(event) {
      const name = event.data?.name ?? ''
      setStatus(TOOL_LABELS[name] ?? `Running ${name}…`)
    }

    function onToken(event) {
      const delta = event.data?.delta ?? ''
      if (!streamingActiveRef.current) {
        streamingActiveRef.current = true
        setStreaming(true)
        setMessages(prev => [
          ...prev,
          { role: 'assistant', type: 'streaming', text: delta },
        ])
      } else {
        setMessages(prev => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last?.type === 'streaming') {
            updated[updated.length - 1] = { ...last, text: last.text + delta }
          }
          return updated
        })
      }
    }

    function onVerdict(event) {
      const v = event.data?.verdict
      if (v) setStatus(`Recommendation verified: ${v}`)
    }

    // Shared teardown: clear streaming bubble and settle state.
    function finalize(replacement) {
      streamingActiveRef.current = false
      setStreaming(false)
      setPending(false)
      setStatus(null)
      setMessages(prev => {
        const base =
          prev[prev.length - 1]?.type === 'streaming' ? prev.slice(0, -1) : prev
        return [...base, replacement]
      })
    }

    function onFinal(event) {
      // event.data is AgentResponse: { text, lang, verdict, citations, session_id }
      finalize({ role: 'assistant', data: event.data })
    }

    function onQuestion(event) {
      finalize({
        role: 'assistant',
        type: 'question',
        text: event.data?.text ?? 'Could you provide more details?',
      })
    }

    function onError(event) {
      finalize({
        role: 'assistant',
        type: 'error',
        text: event.data?.message ?? 'Something went wrong. Please try again.',
      })
    }

    socket.on('phase',     onPhase)
    socket.on('tool_call', onToolCall)
    socket.on('token',     onToken)
    socket.on('verdict',   onVerdict)
    socket.on('final',     onFinal)
    socket.on('question',  onQuestion)
    socket.on('error',     onError)

    return () => {
      socket.off('phase',     onPhase)
      socket.off('tool_call', onToolCall)
      socket.off('token',     onToken)
      socket.off('verdict',   onVerdict)
      socket.off('final',     onFinal)
      socket.off('question',  onQuestion)
      socket.off('error',     onError)
      resetSocket()
    }
  }, [langPref])

  const sendMessage = useCallback(
    text => {
      streamingActiveRef.current = false
      setStreaming(false)
      setStatus(null)
      setMessages(prev => [...prev, { role: 'user', text }])
      setPending(true)
      getSocket().emit('chat', { farmer_id: farmerId, message: text })
    },
    [farmerId],
  )

  return { messages, sendMessage, pending, streaming, status }
}
