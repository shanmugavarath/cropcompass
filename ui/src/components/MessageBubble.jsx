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

  // Standard assistant response with verdict + citations
  return (
    <div className="message-row message-row--assistant">
      <div className="message-bubble message-bubble--assistant">
        <RecommendationCard response={message.data} />
      </div>
    </div>
  )
}
