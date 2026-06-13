import { useState } from 'react'
import LanguageTag from './LanguageTag'

const SAFE_FALLBACK =
  'Please consult your local Krishi Vigyan Kendra for current advice.'

const FLORES_TO_BCP47 = {
  hin_Deva: 'hi',
  tam_Taml: 'ta',
  tel_Telu: 'te',
  mar_Deva: 'mr',
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

export default function RecommendationCard({ response }) {
  const [showCitations, setShowCitations] = useState(false)
  const { text, lang, verdict, citations } = response

  const bcp47 = FLORES_TO_BCP47[lang] ?? 'en'
  const fontClass = FLORES_TO_FONT_CLASS[lang] ?? ''
  const hasCitations = citations && Object.keys(citations).length > 0

  return (
    <div className="rec-card">
      {verdict === 'REJECT' ? (
        <p className="safe-fallback" role="alert">
          {SAFE_FALLBACK}
        </p>
      ) : (
        <p className={`rec-card__text ${fontClass}`} lang={bcp47}>
          {text}
        </p>
      )}

      <div className="rec-card__footer">
        <VerdictBadge verdict={verdict} />
        <LanguageTag lang={lang} />
        {verdict !== 'REJECT' && hasCitations && (
          <button
            className="citations-toggle"
            onClick={() => setShowCitations(s => !s)}
            aria-expanded={showCitations}
            aria-controls="citations-list"
          >
            {showCitations ? 'Hide sources' : 'Sources'}
          </button>
        )}
      </div>

      {showCitations && hasCitations && (
        <ul className="citations-list" id="citations-list">
          {Object.values(citations).map(chunkId => (
            <li key={chunkId}>{chunkId}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
