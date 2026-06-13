import RecommendationCard from './RecommendationCard'

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

  return (
    <div className="message-row message-row--assistant">
      <div className="message-bubble message-bubble--assistant">
        <RecommendationCard response={message.data} />
      </div>
    </div>
  )
}
