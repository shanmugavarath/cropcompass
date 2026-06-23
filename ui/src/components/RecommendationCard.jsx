import { useState, useId } from 'react'
import LanguageTag from './LanguageTag'
import EvalPanel from './EvalPanel'
import Markdown from './Markdown'

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

  const { text, lang, verdict, citations } = response
  const bcp47      = FLORES_TO_BCP47[lang]     ?? 'en'
  const fontClass  = FLORES_TO_FONT_CLASS[lang] ?? ''
  const citationEntries = citations ? Object.entries(citations) : []
  const hasCitations    = citationEntries.length > 0

  const cardClass = verdict === 'PARTIAL' ? 'rec-card rec-card--partial' : 'rec-card'

  return (
    <div className={cardClass}>
      <Markdown text={text} fontClass={fontClass} lang={bcp47} />

      <div className="rec-card__footer">
        <VerdictBadge verdict={verdict} />
        <LanguageTag lang={lang} />

        {hasCitations && (
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
      {question && (
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
