// Minimal, dependency-free markdown renderer for agent answers.
// Handles the subset the planner emits — **bold**, *italic*, `code`, #/##/###
// headings, blank-line paragraphs, and bullet (-, *, •) / numbered (1.) lists,
// including lists that follow a paragraph inside the same block. Renders to React
// elements (no HTML injection) and keeps Indic lang/font handling on the container.
//
// It is line-based and tolerant of partial input, so it can render text WHILE it
// streams in (an unclosed **bold shows literally only until its closer arrives).
//
// For richer markdown (links, tables, blockquotes) swap this for react-markdown;
// the call sites (RecommendationCard, MessageBubble) stay the same.

const HEADING = /^(#{1,6})\s+(.*)$/
const BULLET = /^\s*[-*•]\s+(.*)$/
const ORDERED = /^\s*\d+\.\s+(.*)$/
const INLINE = /(`[^`]+`|\*\*[^*]+?\*\*|\*[^*\s][^*]*?\*|_[^_\s][^_]*?_)/g

function parseInline(text, kp) {
  return text.split(INLINE).map((part, i) => {
    if (!part) return null
    const key = `${kp}-${i}`
    if (part.length > 1 && part.startsWith('`') && part.endsWith('`')) {
      return <code key={key} className="md-code">{part.slice(1, -1)}</code>
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={key}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={key}>{part.slice(1, -1)}</em>
    }
    if (part.startsWith('_') && part.endsWith('_')) {
      return <em key={key}>{part.slice(1, -1)}</em>
    }
    return part
  })
}

export default function Markdown({ text, fontClass = '', lang }) {
  const lines = (text ?? '').replace(/\r\n/g, '\n').split('\n')
  const out = []
  let para = []          // buffered paragraph lines
  let list = null        // { tag: 'ul' | 'ol', items: [] }
  let key = 0

  const flushPara = () => {
    if (!para.length) return
    const k = `p${key++}`
    const nodes = []
    para.forEach((ln, i) => {
      if (i > 0) nodes.push(<br key={`${k}-br${i}`} />)
      nodes.push(...parseInline(ln, `${k}-${i}`))
    })
    out.push(<p key={k} className="md-p">{nodes}</p>)
    para = []
  }
  const flushList = () => {
    if (!list) return
    const k = `l${key++}`
    const Tag = list.tag
    out.push(
      <Tag key={k} className="md-list">
        {list.items.map((it, ii) => <li key={ii}>{parseInline(it, `${k}-${ii}`)}</li>)}
      </Tag>,
    )
    list = null
  }
  const pushItem = (tag, content) => {
    if (list && list.tag !== tag) flushList()
    if (!list) list = { tag, items: [] }
    list.items.push(content)
  }

  for (const line of lines) {
    if (line.trim() === '') { flushPara(); flushList(); continue }

    const h = line.match(HEADING)
    if (h) {
      flushPara(); flushList()
      const lvl = Math.min(h[1].length, 3)
      out.push(
        <p key={`h${key++}`} className={`md-h md-h${lvl}`}>
          {parseInline(h[2], `h${key}`)}
        </p>,
      )
      continue
    }

    const b = line.match(BULLET)
    if (b) { flushPara(); pushItem('ul', b[1]); continue }

    const o = line.match(ORDERED)
    if (o) { flushPara(); pushItem('ol', o[1]); continue }

    flushList()
    para.push(line)
  }
  flushPara(); flushList()

  return (
    <div className={`rec-card__md ${fontClass}`} lang={lang}>
      {out}
    </div>
  )
}
