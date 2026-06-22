import { useState, useId } from 'react'
import LanguageTag from './LanguageTag'
import EvalPanel from './EvalPanel'
import Markdown from './Markdown'
import { useSpeech } from '../hooks/useSpeech'
import STRINGS from '../localization/index'

const SAFE_FALLBACK =
  'Please consult your local Krishi Vigyan Kendra for current advice.'

const FLORES_TO_BCP47 = {
  hin_Deva: 'hi',
  mar_Deva: 'mr',
  tam_Taml: 'ta',
  tel_Telu: 'te',
  pan_Guru: 'pa',
  eng_Latn: 'en',
}

const FLORES_TO_FONT_CLASS = {
  hin_Deva: 'rec-card__text--deva',
  mar_Deva: 'rec-card__text--deva',
  tam_Taml: 'rec-card__text--taml',
  tel_Telu: 'rec-card__text--telu',
  pan_Guru: 'rec-card__text--guru',
  eng_Latn: '',
}

const VERDICT_CONFIG = {
  PASS:    { cls: 'verdict-badge--pass',    icon: '✓', label: 'Verified' },
  PARTIAL: { cls: 'verdict-badge--partial', icon: '⚠', label: 'Some advice unverified' },
  REJECT:  { cls: 'verdict-badge--reject',  icon: '✕', label: 'Unverified' },
}

function VerdictBadge({ verdict }) {
  const { cls, icon, label } = VERDICT_CONFIG[verdict] ?? { cls: '', icon: '', label: verdict }
  return (
    <span className={`verdict-badge ${cls}`} role="status">
      <span aria-hidden="true">{icon}</span>
      {label}
    </span>
  )
}

export default function RecommendationCard({ response, question, farmerId }) {
  const [showCitations, setShowCitations] = useState(false)
  // useId gives a unique ID per card instance — safe for aria-controls when
  // multiple RecommendationCards appear in the same message list
  const citationsId = useId()
  const { speaking, speak, stop } = useSpeech()

  const { text, lang, verdict, citations } = response
  const bcp47      = FLORES_TO_BCP47[lang]     ?? 'en'
  const fontClass  = FLORES_TO_FONT_CLASS[lang] ?? ''
  const citationEntries = citations ? Object.entries(citations) : []
  const hasCitations    = citationEntries.length > 0

  const cardClass = verdict === 'PARTIAL' ? 'rec-card rec-card--partial' : 'rec-card'

  const strings     = STRINGS[lang] ?? STRINGS.eng_Latn
  const listenLabel = strings.listenLabel ?? 'Listen'
  const stopLabel   = strings.stopLabel   ?? 'Stop'

  function handleListen() {
    if (speaking) stop()
    else speak(text, lang)
  }

  return (
    <div className={cardClass}>
      {verdict === 'REJECT' ? (
        <p className="safe-fallback" role="alert">
          {SAFE_FALLBACK}
        </p>
      ) : (
        <Markdown text={text} fontClass={fontClass} lang={bcp47} />
      )}

      <div className="rec-card__footer">
        <VerdictBadge verdict={verdict} />
        <LanguageTag lang={lang} />

        {/* Listen button — always shown for non-REJECT responses */}
        {verdict !== 'REJECT' && (
          <button
            className={`listen-btn${speaking ? ' listen-btn--active' : ''}`}
            onClick={handleListen}
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
        )}

        {verdict !== 'REJECT' && hasCitations && (
          <button
            className="citations-toggle"
            onClick={() => setShowCitations(s => !s)}
            aria-expanded={showCitations}
            aria-controls={citationsId}
          >
            {showCitations ? 'Hide sources' : `Sources (${citationEntries.length})`}
          </button>
        )}
      </div>

      {/* Citations: claim text as readable label, chunk_id as monospace reference */}
      {showCitations && hasCitations && (
        <ul className="citations-list" id={citationsId} aria-label="Sources">
          {citationEntries.map(([claim, chunkId]) => (
            <li key={chunkId} className="citation-item">
              <span className="citation-item__claim">{claim}</span>
              <span className="citation-item__chunk">{chunkId}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Eval harness: "How this was evaluated" — judges THIS answer live */}
      {verdict !== 'REJECT' && question && (
        <EvalPanel
          question={question}
          answer={text}
          farmerId={farmerId}
          verdict={verdict}
          citations={citations}
        />
      )}
    </div>
  )
}
