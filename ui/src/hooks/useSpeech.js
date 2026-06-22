import { useState, useEffect, useRef, useCallback } from 'react'
import { FLORES_TO_BCP47 } from '../localization/langCodes'

/**
 * Strip markdown tokens before passing text to speechSynthesis so the synth
 * reads clean prose instead of reading out "asterisk asterisk" etc.
 */
function stripMarkdown(text) {
  return text
    .replace(/#{1,3}\s*/g,        '')   // headings
    .replace(/\*\*(.*?)\*\*/g,  '$1')  // bold
    .replace(/\*(.*?)\*/g,      '$1')  // italic
    .replace(/_(.*?)_/g,        '$1')  // italic underscore
    .replace(/`([^`]+)`/g,      '$1')  // inline code
    .replace(/^[-*•]\s+/gm,      '')   // list bullets
    .replace(/^\d+\.\s+/gm,      '')   // numbered lists
    .trim()
}

/**
 * Text-to-speech hook wrapping the browser SpeechSynthesis API.
 *
 * @returns {{ supported: boolean, speaking: boolean, speak: (text: string, floresLang: string) => void, stop: () => void }}
 */
export function useSpeech() {
  const [speaking, setSpeaking] = useState(false)
  const voicesRef  = useRef([])

  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window

  // Voices load async on first access; refresh when voiceschanged fires
  useEffect(() => {
    if (!supported) return

    function loadVoices() {
      voicesRef.current = window.speechSynthesis.getVoices()
    }

    loadVoices()
    window.speechSynthesis.addEventListener('voiceschanged', loadVoices)
    return () => window.speechSynthesis.removeEventListener('voiceschanged', loadVoices)
  }, [supported])

  const speak = useCallback((text, floresLang = 'eng_Latn') => {
    if (!supported || !text) return

    // Cancel any ongoing speech before starting new one
    window.speechSynthesis.cancel()

    const bcp47 = FLORES_TO_BCP47[floresLang] ?? 'en'
    const clean = stripMarkdown(text)
    const utt   = new SpeechSynthesisUtterance(clean)

    // Prefer a voice whose lang code starts with the target language
    const match = voicesRef.current.find(
      v => v.lang.toLowerCase().startsWith(bcp47.toLowerCase())
    )
    if (match) {
      utt.voice = match
    } else {
      // Fall back to setting lang so the browser picks the best available
      utt.lang = `${bcp47}-IN`
    }

    utt.rate   = 0.92  // slightly slower — easier for farmers to follow
    utt.pitch  = 1.0
    utt.volume = 1.0

    utt.onstart = () => setSpeaking(true)
    utt.onend   = () => setSpeaking(false)
    utt.onerror = () => setSpeaking(false)

    window.speechSynthesis.speak(utt)
  }, [supported])

  const stop = useCallback(() => {
    if (!supported) return
    window.speechSynthesis.cancel()
    setSpeaking(false)
  }, [supported])

  return { supported, speaking, speak, stop }
}
