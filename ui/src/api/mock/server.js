import { http, HttpResponse } from 'msw'
import { setupWorker } from 'msw/browser'

const BASE = import.meta.env.VITE_API_URL

// Canned responses cycling through all three verdict paths (PASS → PARTIAL → REJECT)
const MOCK_RESPONSES = [
  {
    text: 'अभी बुवाई करें और खाद की मात्रा बढ़ाएं। IMD के अनुसार अगले सप्ताह अच्छी वर्षा की संभावना है।',
    lang: 'hin_Deva',
    verdict: 'PASS',
    citations: {
      'बुवाई का सही समय': 'icar_chunk_001',
      'खाद की मात्रा': 'icar_chunk_042',
    },
    session_id: 'mock-session-001',
  },
  {
    text: 'सिंचाई के लिए सुबह का समय उचित है। कुछ सिफारिशें पूरी तरह सत्यापित नहीं हो सकीं।',
    lang: 'hin_Deva',
    verdict: 'PARTIAL',
    citations: { 'सिंचाई समय': 'icar_chunk_017' },
    session_id: 'mock-session-002',
  },
  {
    // REJECT — text is intentionally empty; UI must never show raw rejected advice
    text: '',
    lang: 'hin_Deva',
    verdict: 'REJECT',
    citations: {},
    session_id: 'mock-session-003',
  },
]

let mockCallCount = 0

export const handlers = [
  http.get(`${BASE}/api/districts`, () =>
    HttpResponse.json({
      districts: [
        'Ahmedabad', 'Amravati', 'Aurangabad', 'Bangalore', 'Bhopal',
        'Chennai', 'Coimbatore', 'Hyderabad', 'Indore', 'Jaipur',
        'Kolkata', 'Lucknow', 'Mumbai', 'Nagpur', 'Nashik',
        'Patna', 'Pune', 'Raipur', 'Ranchi', 'Surat',
        'Vadodara', 'Varanasi', 'Vijayawada', 'Visakhapatnam',
      ],
    })
  ),

  http.post(`${BASE}/api/profile`, async ({ request }) => {
    const body = await request.json()
    return HttpResponse.json({
      ...body,
      farmer_id: `mock-farmer-${crypto.randomUUID().slice(0, 8)}`,
    })
  }),

  http.get(`${BASE}/api/profile/:farmerId`, ({ params }) =>
    HttpResponse.json({
      farmer_id: params.farmerId,
      district: 'Pune',
      soil_type: 'clay_loam',
      crop_variety: 'Soybean JS-335',
      growth_stage: 'sowing',
      lang_pref: 'hin_Deva',
    })
  ),

  http.get(`${BASE}/api/forecast/:district`, ({ params }) =>
    HttpResponse.json({
      district: params.district,
      bulletin: 'मध्यम वर्षा की संभावना। तापमान 28–34°C।',
      issued_at: new Date().toISOString(),
    })
  ),

  http.post(`${BASE}/api/chat`, async () => {
    const response = MOCK_RESPONSES[mockCallCount % MOCK_RESPONSES.length]
    mockCallCount++
    return HttpResponse.json(response)
  }),
]

export const worker = setupWorker(...handlers)

// Mock socket — emits StreamEvent frames matching the agent's wire protocol.
// Sequence per chat message:
//   phase(gather) → tool_call → tool_result → phase(generate)
//   → token × N → phase(verify) → verdict → phase(translate) → final
export function getMockSocket() {
  const listeners = {}

  function dispatch(type, data, sid) {
    const frame = { type, data, session_id: sid }
    ;(listeners[type] ?? []).forEach(h => h(frame))
  }

  function emitStream(response, sid) {
    const words = response.text
      ? response.text.split(' ')
      : ['Please', 'consult', 'your', 'local', 'Krishi', 'Vigyan', 'Kendra.']

    let t = 0
    const step = ms => { t += ms; return t }

    setTimeout(() => dispatch('phase',       { phase: 'gather' }, sid),                                        step(120))
    setTimeout(() => dispatch('tool_call',   { name: 'get_farmer_profile' }, sid),                             step(80))
    setTimeout(() => dispatch('tool_result', { name: 'get_farmer_profile',   ok: true, preview: 'district: Pune' }, sid), step(200))
    setTimeout(() => dispatch('tool_call',   { name: 'fetch_latest_advisory' }, sid),                          step(60))
    setTimeout(() => dispatch('tool_result', { name: 'fetch_latest_advisory', ok: true, preview: 'moderate rainfall expected' }, sid), step(250))
    setTimeout(() => dispatch('tool_call',   { name: 'query_knowledge_base' }, sid),                           step(60))
    setTimeout(() => dispatch('tool_result', { name: 'query_knowledge_base',  ok: true, preview: '5 chunks retrieved' }, sid), step(300))
    setTimeout(() => dispatch('phase',       { phase: 'generate' }, sid),                                      step(80))

    // Stream response text word by word
    words.forEach((word, i) => {
      setTimeout(
        () => dispatch('token', { delta: (i === 0 ? '' : ' ') + word }, sid),
        step(60),
      )
    })

    setTimeout(() => dispatch('phase',   { phase: 'verify' }, sid),                                           step(150))
    setTimeout(() => dispatch('verdict', { verdict: response.verdict, citations: response.citations ?? {} }, sid), step(200))
    setTimeout(() => dispatch('phase',   { phase: 'translate' }, sid),                                        step(80))
    setTimeout(() => dispatch('final', {
      text:       response.text,
      lang:       response.lang,
      verdict:    response.verdict,
      citations:  response.citations ?? {},
      session_id: sid,
    }, sid), step(200))
  }

  return {
    on(event, handler) {
      if (!listeners[event]) listeners[event] = []
      listeners[event].push(handler)
    },
    off(event, handler) {
      if (listeners[event]) {
        listeners[event] = listeners[event].filter(h => h !== handler)
      }
    },
    emit(event) {
      if (event === 'chat') {
        const response = MOCK_RESPONSES[mockCallCount % MOCK_RESPONSES.length]
        mockCallCount++
        const sid = `mock-session-${mockCallCount.toString().padStart(3, '0')}`
        emitStream(response, sid)
      }
    },
    disconnect() {},
    connected: true,
  }
}
