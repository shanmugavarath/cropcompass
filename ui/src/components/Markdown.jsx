// Minimal, dependency-free markdown renderer for agent answers.
// Handles the subset the planner emits: **bold**, blank-line paragraphs, and
// simple bullet (-, *, •) / numbered (1.) lists. Renders to React elements
// (no HTML injection), and keeps Indic lang/font handling on the container.
//
// If richer markdown (headings, links, tables) is ever needed, swap this for
// react-markdown — the call site (RecommendationCard) stays the same.

const BOLD_SPLIT = /(\*\*[^*]+?\*\*)/g
const BULLET = /^\s*[-*•]\s+/
const ORDERED = /^\s*\d+\.\s+/

function parseInline(text, kp) {
  return text.split(BOLD_SPLIT).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${kp}-${i}`}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

function Paragraph({ block, kp }) {
  const lines = block.split('\n')
  const nodes = []
  lines.forEach((line, i) => {
    if (i > 0) nodes.push(<br key={`${kp}-br-${i}`} />)
    nodes.push(...parseInline(line, `${kp}-${i}`))
  })
  return <p className="md-p">{nodes}</p>
}

export default function Markdown({ text, fontClass = '', lang }) {
  const blocks = (text ?? '').trim().split(/\n{2,}/).filter(Boolean)

  return (
    <div className={`rec-card__md ${fontClass}`} lang={lang}>
      {blocks.map((block, bi) => {
        const lines = block.split('\n').filter((l) => l.trim() !== '')
        const allBullet = lines.length > 0 && lines.every((l) => BULLET.test(l))
        const allOrdered = lines.length > 0 && lines.every((l) => ORDERED.test(l))

        if (allBullet) {
          return (
            <ul key={bi} className="md-list">
              {lines.map((l, li) => (
                <li key={li}>{parseInline(l.replace(BULLET, ''), `b${bi}-${li}`)}</li>
              ))}
            </ul>
          )
        }
        if (allOrdered) {
          return (
            <ol key={bi} className="md-list">
              {lines.map((l, li) => (
                <li key={li}>{parseInline(l.replace(ORDERED, ''), `o${bi}-${li}`)}</li>
              ))}
            </ol>
          )
        }
        return <Paragraph key={bi} block={block} kp={`p${bi}`} />
      })}
    </div>
  )
}
