import RecommendationCard from './RecommendationCard'
import Markdown from './Markdown'
import { useSpeech } from '../hooks/useSpeech'
import STRINGS from '../localization/index'

const FLORES_TO_BCP47 = {
  hin_Deva: 'hi', mar_Deva: 'mr',
  tam_Taml: 'ta', tel_Telu: 'te',
  pan_Guru: 'pa', eng_Latn: 'en',
}

const FLORES_TO_FONT_CLASS = {
  hin_Deva: 'rec-card__text--deva', mar_Deva: 'rec-card__text--deva',
  tam_Taml: 'rec-card__text--taml', tel_Telu: 'rec-card__text--telu',
  pan_Guru: 'rec-card__text--guru', eng_Latn: '',
}

/** Inline listen button reused for greeting and question bubbles */
function ListenButton({ text, lang }) {
  const { speaking, speak, stop } = useSpeech()
  const strings     = STRINGS[lang] ?? STRINGS.eng_Latn
  const listenLabel = strings.listenLabel ?? 'Listen'
  const stopLabel   = strings.stopLabel   ?? 'Stop'

  return (
    <button
      className={`listen-btn listen-btn--inline${speaking ? ' listen-btn--active' : ''}`}
      onClick={() => speaking ? stop() : speak(text, lang)}
      aria-label={speaking ? stopLabel : listenLabel}
      aria-pressed={speaking}
      type="button"
    >
      {speaking ? (
        <svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13" aria-hidden="true">
          <path d="M6 6h12v12H6z"/>
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13" aria-hidden="true">
          <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
        </svg>
      )}
      <span>{speaking ? stopLabel : listenLabel}</span>
    </button>
  )
}

export default function MessageBubble({ message }) {
  if (message.role === 'user') {
    return (
      <div className="message-row message-row--user">
        <div className="message-bubble message-bubble--user">
          {message.text}
        </div>
      </div>
    )
  }

  // Initial greeting — plain card, no verdict badge or citations
  if (message.type === 'greeting') {
    const bcp47 = FLORES_TO_BCP47[message.lang] ?? 'hi'
    const fontClass = FLORES_TO_FONT_CLASS[message.lang] ?? ''
    return (
      <div className="message-row message-row--assistant">
        <div className="message-bubble message-bubble--assistant">
          <p
            className={`rec-card__text ${fontClass}`}
            lang={bcp47}
            style={{ padding: '14px 16px', marginBottom: 0 }}
          >
            {message.text}
          </p>
          <div className="bubble-listen-row">
            <ListenButton text={message.text} lang={message.lang ?? 'eng_Latn'} />
          </div>
        </div>
      </div>
    )
  }

  // In-progress streaming bubble — text grows token by token, rendered as
  // markdown so the farmer never sees raw ** / # syntax mid-stream.
  if (message.type === 'streaming') {
    return (
      <div className="message-row message-row--assistant">
        <div className="message-bubble message-bubble--assistant message-bubble--streaming">
          <Markdown text={message.text} />
          <span className="streaming-cursor" aria-hidden="true" />
        </div>
      </div>
    )
  }

  // Clarification question from the agent
  if (message.type === 'question') {
    return (
      <div className="message-row message-row--assistant">
        <div className="message-bubble message-bubble--assistant message-bubble--question">
          {message.text}
          <div className="bubble-listen-row">
            <ListenButton text={message.text} lang={message.lang ?? 'eng_Latn'} />
          </div>
        </div>
      </div>
    )
  }

  // Error from the agent or network
  if (message.type === 'error') {
    return (
      <div className="message-row message-row--assistant">
        <div
          className="message-bubble message-bubble--assistant message-bubble--error"
          role="alert"
        >
          {message.text}
        </div>
      </div>
    )
  }

  // Standard assistant response with verdict + citations
  return (
    <div className="message-row message-row--assistant">
      <div className="message-bubble message-bubble--assistant">
        <RecommendationCard
          response={message.data}
          question={message.question}
          farmerId={message.farmerId}
        />
      </div>
    </div>
  )
}
