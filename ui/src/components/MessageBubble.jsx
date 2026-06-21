import RecommendationCard from './RecommendationCard'

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
        </div>
      </div>
    )
  }

  // In-progress streaming bubble — text grows token by token
  if (message.type === 'streaming') {
    return (
      <div className="message-row message-row--assistant">
        <div className="message-bubble message-bubble--assistant message-bubble--streaming">
          <span>{message.text}</span>
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
        <RecommendationCard response={message.data} />
      </div>
    </div>
  )
}
