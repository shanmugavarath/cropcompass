import { http, HttpResponse } from 'msw'
import { setupWorker } from 'msw/browser'

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
  http.get('/api/districts', () =>
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

  http.post('/api/profile', async ({ request }) => {
    const body = await request.json()
    return HttpResponse.json({
      ...body,
      farmer_id: `mock-farmer-${crypto.randomUUID().slice(0, 8)}`,
    })
  }),

  http.get('/api/profile/:farmerId', ({ params }) =>
    HttpResponse.json({
      farmer_id: params.farmerId,
      district: 'Pune',
      soil_type: 'clay_loam',
      crop_variety: 'Soybean JS-335',
      growth_stage: 'sowing',
      lang_pref: 'hin_Deva',
    })
  ),

  http.get('/api/forecast/:district', ({ params }) =>
    HttpResponse.json({
      district: params.district,
      bulletin: 'मध्यम वर्षा की संभावना। तापमान 28–34°C।',
      issued_at: new Date().toISOString(),
    })
  ),

  http.post('/api/chat', async () => {
    const response = MOCK_RESPONSES[mockCallCount % MOCK_RESPONSES.length]
    mockCallCount++
    return HttpResponse.json(response)
  }),
]

export const worker = setupWorker(...handlers)

// Mock socket — mimics socket.io-client API; replies ~800ms after 'chat' emit
export function getMockSocket() {
  const listeners = {}

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
        setTimeout(() => {
          const response = MOCK_RESPONSES[mockCallCount % MOCK_RESPONSES.length]
          mockCallCount++
          ;(listeners['response'] ?? []).forEach(h => h(response))
        }, 800)
      }
    },
    disconnect() {},
    connected: true,
  }
}
