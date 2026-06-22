// Client for the agent's POST /api/evaluate — runs the eval harness's LLM-judge
// on a live answer. The endpoint lives on the AGENT service (port 8001), not the
// REST api (8000), so derive its base from the WS URL (or VITE_AGENT_URL).
export const AGENT_BASE =
  import.meta.env.VITE_AGENT_URL ||
  (import.meta.env.VITE_WS_URL || 'ws://localhost:8001').replace(/^ws(s?):/, 'http$1:')

export async function evaluateAnswer({ message, answer, farmerId, verdict, citations }) {
  const res = await fetch(`${AGENT_BASE}/api/evaluate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      answer,
      farmer_id: farmerId ?? null,
      verdict: verdict ?? null,
      citations: citations ?? {},
    }),
  })
  if (!res.ok) throw new Error(`Evaluation failed (${res.status})`)
  const data = await res.json()
  if (data.error) throw new Error(data.error)
  return data
}
