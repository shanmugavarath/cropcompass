import { useState, useRef, useEffect } from 'react'
import { FLORES_TO_SPEECH_LOCALE } from '../localization/langCodes'

const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition)

/**
 * Speech-to-text hook wrapping the browser SpeechRecognition API.
 *
 * @param {string} floresLang - FLORES-200 code, e.g. 'hin_Deva'
 * @returns {{ supported: boolean, listening: boolean, transcript: string, error: string|null, start: () => void, stop: () => void }}
 */
export function useSpeechInput(floresLang = 'eng_Latn') {
  const [listening, setListening]   = useState(false)
  const [transcript, setTranscript] = useState('')
  const [error, setError]           = useState(null)
  const recRef = useRef(null)

  const supported = Boolean(SpeechRecognition)

  useEffect(() => {
    if (!supported) return

    const rec = new SpeechRecognition()
    rec.lang = FLORES_TO_SPEECH_LOCALE[floresLang] ?? 'en-IN'
    rec.interimResults  = true
    rec.continuous      = false
    rec.maxAlternatives = 1

    rec.onstart = () => { setListening(true); setError(null) }
    rec.onend   = () => setListening(false)
    rec.onerror = (e) => {
      setListening(false)
      // 'no-speech' is not a real error; ignore it silently
      if (e.error !== 'no-speech') setError(e.error)
    }

    rec.onresult = (e) => {
      let interim = ''
      let final   = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript
        if (e.results[i].isFinal) final  += t
        else                       interim += t
      }
      // Prefer a finalized result; fall back to interim so text appears live
      setTranscript(final || interim)
    }

    recRef.current = rec

    return () => {
      try { rec.abort() } catch (_) { /* already stopped */ }
    }
  }, [floresLang, supported])

  function start() {
    if (!supported || !recRef.current) return
    setTranscript('')
    setError(null)
    try { recRef.current.start() } catch (_) { /* already started */ }
  }

  function stop() {
    if (!supported || !recRef.current) return
    try { recRef.current.stop() } catch (_) { /* already stopped */ }
  }

  return { supported, listening, transcript, error, start, stop }
}
