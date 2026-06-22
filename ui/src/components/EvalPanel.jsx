import { useState } from 'react'
import { evaluateAnswer } from '../api/evaluate'

const VERDICT_EXPLAIN = {
  PASS: 'Every claim was grounded in a retrieved source.',
  PARTIAL: 'Some claims were grounded; unverified ones were removed before showing the advice.',
  REJECT: 'No claims could be grounded, so a safe fallback was shown instead.',
}

function ScoreBar({ label, value, max = 5, hint }) {
  const pct = Math.max(0, Math.min(100, (Number(value) / max) * 100))
  return (
    <div className="eval-score">
      <div className="eval-score__head">
        <span className="eval-score__label">
          {label}
          {hint && <span className="eval-score__hint"> · {hint}</span>}
        </span>
        <span className="eval-score__value">{value}/{max}</span>
      </div>
      <div className="eval-score__track">
        <div className="eval-score__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/**
 * "How this was evaluated" — runs the eval harness's LLM-as-judge on THIS answer
 * (via POST /api/evaluate) and presents grounding, retrieval and judge scores in
 * an accordion. Lazily fetches on first expand.
 */
export default function EvalPanel({ question, answer, farmerId, verdict, citations }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState({ status: 'idle', data: null, error: null })

  async function handleToggle() {
    const next = !open
    setOpen(next)
    if (next && state.status === 'idle') {
      setState({ status: 'loading', data: null, error: null })
      try {
        const data = await evaluateAnswer({ message: question, answer, farmerId, verdict, citations })
        setState({ status: 'done', data, error: null })
      } catch (e) {
        setState({ status: 'error', data: null, error: e.message })
      }
    }
  }

  const { status, data, error } = state
  const judge = data?.judge
  const chunks = data?.retrieval?.chunks ?? []
  const citationCount = citations ? Object.keys(citations).length : 0

  return (
    <div className="eval-panel">
      <button className="eval-toggle" onClick={handleToggle} aria-expanded={open}>
        <span aria-hidden="true">🔬</span> {open ? 'Hide evaluation' : 'How this was evaluated'}
      </button>

      {open && (
        <div className="eval-body">
          {status === 'loading' && (
            <p className="eval-status">Running the eval harness on this answer…</p>
          )}
          {status === 'error' && (
            <p className="eval-status eval-status--error" role="alert">
              Could not evaluate: {error}
            </p>
          )}
          {status === 'done' && judge && (
            <div className="eval-accordion">
              {/* 1 — Grounding (live verifier verdict) */}
              <details className="eval-item" open>
                <summary className="eval-item__summary">
                  <span>Grounding</span>
                  <span className={`verdict-badge verdict-badge--${(verdict || '').toLowerCase()}`}>
                    {verdict}
                  </span>
                </summary>
                <div className="eval-item__body">
                  <p>{VERDICT_EXPLAIN[verdict] ?? 'Grounding verdict from the verifier.'}</p>
                  {citationCount > 0 && (
                    <p className="eval-note">{citationCount} claim(s) cited to sources.</p>
                  )}
                </div>
              </details>

              {/* 2 — Retrieval (what the answer was grounded against) */}
              <details className="eval-item">
                <summary className="eval-item__summary">
                  <span>Retrieval</span>
                  <span className="eval-count">{data.retrieval.count} source(s)</span>
                </summary>
                <div className="eval-item__body">
                  <p className="eval-note">Top sources retrieved for the question (semantic similarity).</p>
                  <ul className="eval-chunks">
                    {chunks.map((c) => (
                      <li key={c.chunk_id} className="eval-chunk">
                        <div className="eval-chunk__head">
                          <span className="citation-item__chunk">{c.chunk_id}</span>
                          <span className="eval-chunk__sim">{Math.round(c.similarity * 100)}%</span>
                        </div>
                        <div className="eval-score__track">
                          <div className="eval-score__fill" style={{ width: `${Math.round(c.similarity * 100)}%` }} />
                        </div>
                        {c.text && <p className="eval-chunk__text">{c.text}</p>}
                      </li>
                    ))}
                  </ul>
                </div>
              </details>

              {/* 3 — Answer quality (LLM-as-judge) */}
              <details className="eval-item">
                <summary className="eval-item__summary">
                  <span>Answer quality</span>
                  <span className="eval-count">LLM-as-judge</span>
                </summary>
                <div className="eval-item__body">
                  <ScoreBar label="Relevance" value={judge.relevance} />
                  <ScoreBar label="Faithfulness" value={judge.faithfulness} />
                  {!data.reference_available && (
                    <p className="eval-note">
                      Correctness &amp; completeness are judged without a reference answer
                      (plausibility only):
                    </p>
                  )}
                  <ScoreBar
                    label="Correctness"
                    value={judge.correctness}
                    hint={data.reference_available ? null : 'no reference'}
                  />
                  <ScoreBar
                    label="Completeness"
                    value={judge.completeness}
                    hint={data.reference_available ? null : 'no reference'}
                  />
                  {judge.rationale && <p className="eval-rationale">“{judge.rationale}”</p>}
                  <p className="eval-foot">Scored by the CropCompass eval harness on this answer.</p>
                </div>
              </details>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
