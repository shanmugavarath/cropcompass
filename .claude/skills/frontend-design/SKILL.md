---
name: frontend-design
description: Build CropCompass UI components and pages — the multilingual agricultural advisory chat app for Indian smallholder farmers. Covers the Vite+React stack, Indic script rendering, chat interface, farmer onboarding wizard, and recommendation display. Use when building any part of the `ui/` directory.
license: Complete terms in LICENSE.txt
---

Build production-grade UI for **CropCompass** — a multilingual agentic agricultural advisory system for Indian smallholder farmers. Every piece of UI you create must feel trustworthy, accessible to users with limited digital literacy, and render Indic scripts flawlessly.

## Project Context

**Who uses this:** Rural Indian farmers checking crop advisories in their native language (Hindi, Tamil, Telugu, Marathi, Punjabi). Many users have low digital literacy and may be on modest Android phones on a slow connection.

**What it does:** Farmer types a question in their language → planning agent fetches IMD forecasts + ICAR knowledge base → verification agent checks it → UI renders the response in Indic script with citations and a PASS/PARTIAL/REJECT verdict badge.

**Stack:**
- `ui/` — Vite + React (TypeScript)
- Backend transport — Socket.IO (`chat` emit, `response` listen) + FastAPI REST
- Mock backend — MSW (controlled via `VITE_USE_MOCK=true`)
- Styling — Tailwind CSS (preferred) or CSS modules; no vanilla CSS soup

**Key components to build:**

| Component | Location | Purpose |
|-----------|----------|---------|
| `ChatWindow` | `ui/src/components/ChatWindow.tsx` | Main chat interface, message list + input bar |
| `MessageBubble` | `ui/src/components/MessageBubble.tsx` | Single message; handles Indic text, RTL-like script |
| `RecommendationCard` | `ui/src/components/RecommendationCard.tsx` | Structured advisory with verdict badge + citations |
| `OnboardingWizard` | `ui/src/components/OnboardingWizard.tsx` | 3-step farmer profile capture (district → soil/crop → language) |
| `LanguagePicker` | `ui/src/components/LanguagePicker.tsx` | FLORES-200 code selector shown in native script |

**AgentResponse shape** (what the backend emits on the `response` Socket.IO event):
```ts
interface AgentResponse {
  text: string;         // already translated to farmer's lang_pref
  lang: string;         // FLORES-200 code e.g. "hin_Deva"
  verdict: "PASS" | "PARTIAL" | "REJECT";
  citations: Record<string, string>; // claim text → chunk_id
  session_id: string;
}
```

**FarmerCreate schema** (POST `/api/profile`):
```ts
interface FarmerCreate {
  district: string;
  soil_type: "clay" | "loam" | "sandy" | "clay_loam" | "silt_loam";
  crop_variety: string;
  growth_stage: "sowing" | "vegetative" | "flowering" | "maturity";
  lang_pref: "hin_Deva" | "tam_Taml" | "tel_Telu" | "mar_Deva" | "pan_Guru" | "eng_Latn";
}
```

## Design Direction

**Aesthetic:** Organic-agricultural. The UI should feel like a trusted extension service, not a Silicon Valley SaaS product. Think handmade paper textures, earthy warmth, and the quiet confidence of a knowledgeable agronomist — not dashboards and growth metrics.

**Palette (mandatory starting point — you may refine, not abandon):**
- Background: warm off-white `#F7F3EE` or deep soil `#1C1410` (dark mode)
- Primary green: `#3A7D44` (field green) — used for send button, active states
- Accent: `#C8871A` (harvest amber) — verdict PASS badges, CTAs
- Warning: `#B85C38` (terracotta) — REJECT badges, errors
- Neutral: `#6B5B4E` (warm brown) — body text, borders

**Typography (mandatory — never use Inter, Roboto, Arial, or system fonts):**
- Display / headings: **Playfair Display** (editorial weight, botanical-catalog feel)
- Body / UI: **DM Sans** (clean, friendly, slightly quirky)
- Indic script: **Noto Sans** with the relevant subset loaded — `Noto Sans Devanagari`, `Noto Sans Tamil`, `Noto Sans Telugu`, `Noto Sans Gurmukhi`, `Noto Sans Malayalam`. Always pair the Indic subset alongside DM Sans so mixed-script text (English labels + Indic responses) renders consistently.

Load fonts via Google Fonts import — example:
```css
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=DM+Sans:wght@400;500&family=Noto+Sans+Devanagari:wght@400;500&family=Noto+Sans+Tamil:wght@400;500&family=Noto+Sans+Telugu:wght@400;500&family=Noto+Sans+Gurmukhi:wght@400;500&display=swap');
```

**Visual language:**
- Subtle grain texture on backgrounds (CSS `filter: url(#grain)` or a semi-transparent PNG overlay) — evokes uncoated paper / soil
- Chat bubbles: farmer messages right-aligned with amber accent; agent responses left-aligned in a card with a soft green left-border
- RecommendationCard gets a visible `verdict` badge: green leaf icon for PASS, amber warning for PARTIAL, terracotta X for REJECT
- Generous line-height (1.7+) for Indic text — these scripts need breathing room
- Onboarding: full-screen step-by-step wizard, progress bar at top, large touch targets (min 48×48px tap areas) for mobile farmers

**What to avoid:**
- Purple gradients, glassmorphism, neon accents — nothing that screams "AI startup"
- Dense information layouts — one thing per screen on mobile
- Latin-only font stacks that leave Indic text falling back to system fonts

## Indic Script Rules

1. Always set `lang` attribute on the element wrapping Indic text: `<p lang="hi">` for Hindi, `<p lang="ta">` for Tamil, etc. Map FLORES codes → BCP-47 tags.
2. Use `unicode-bidi: embed` for mixed-script content.
3. Set `font-family` to the Noto subset first, then DM Sans as fallback: `font-family: 'Noto Sans Devanagari', 'DM Sans', sans-serif`.
4. Never truncate Indic text with `text-overflow: ellipsis` — matras get clipped; use line-clamping instead.
5. Test every text-displaying component with a real Hindi string like `"अभी बुवाई करें और खाद की मात्रा बढ़ाएं"` to catch font-loading failures early.

## Mock Backend (MSW)

When building any component that touches the network, wire it against the MSW mock first. The mock lives at `ui/src/mocks/`. A Socket.IO handler should emit a canned `AgentResponse` ~800ms after receiving a `chat` event — simulating real latency.

Use `VITE_USE_MOCK=true` in `.env.local` to activate. The real backend swap at integration time should require zero component changes.

## Accessibility

- Minimum tap target 48×48px — many users on touchscreens
- Contrast ratio ≥ 4.5:1 for all text (verify with the earthy palette)
- Don't rely on color alone to convey verdict — pair with icon + text label
- `aria-live="polite"` on the message list so screen readers announce incoming responses
- All form fields in OnboardingWizard need associated `<label>` elements

## Implementation Notes

- Use React Query (or SWR) for REST calls; the `useSocket` hook for Socket.IO events
- Keep component state minimal — `farmer_id` in localStorage after onboarding, nothing else global
- The `OnboardingWizard` should redirect to `ChatWindow` after profile creation and pass `farmer_id` via router state
- Lazy-load the Noto font subsets — only load the subset matching the farmer's `lang_pref`
