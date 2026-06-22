# CropCompass — Wow-Factor Features

High-impact features to elevate CropCompass from "another chatbot" into a product that
non-literate Indian smallholder farmers can genuinely use. Each idea is grounded in the
existing stack (4-phase agentic loop, multilingual RAG, citations, verification, 9 Indic
languages, IMD/ICAR data pipelines).

**Stack reference (verified):**
- Chat flow: `InputBar.onSend()` → `useChat.sendMessage()` → `socket.emit('chat', {farmer_id, message})`
  → backend streams `StreamEvent`s → `useChat` listeners update state → `MessageBubble` →
  `RecommendationCard`.
- Stream events: `phase`, `tool_call`, `tool_result`, `token`, `verdict`, `final`, `question`, `error`.
- `AgentResponse`: `{ text, lang, verdict ('PASS'|'PARTIAL'|'REJECT'), citations {claim: chunk_id}, session_id }`.
- 9 FLORES languages: `hin_Deva, mar_Deva, tam_Taml, tel_Telu, pan_Guru, ben_Beng, kan_Knda, mal_Mlym, eng_Latn`.

---

## 1. Voice-First Interaction *(highest wow-per-effort)*

Most smallholder farmers have low literacy — text chat is a barrier, voice is the killer feature.
Goal: a mic button to **speak a question** and a speaker button to **hear the answer**, both in the
farmer's selected language (`lang_pref` from `localStorage`).

### 1a. Speech-to-Text (mic in `InputBar.jsx`)

1. Create a hook `ui/src/hooks/useSpeechInput.js` wrapping the browser
   `SpeechRecognition` / `webkitSpeechRecognition` API.
   - Accept a `lang` arg (BCP47, e.g. `hi`, `mr`, `ta`) — reuse the FLORES→BCP47 map already in
     `MessageBubble.jsx` (`hin_Deva→hi`, etc.). Export that map to a shared `ui/src/localization/langCodes.js`
     so both components share one source of truth.
   - Return `{ supported, listening, transcript, start(), stop(), error }`.
   - Set `recognition.lang = bcp47`, `recognition.interimResults = true`, `recognition.continuous = false`.
2. In `InputBar.jsx`:
   - Add a mic button next to send. Pass `langPref` down from `ChatWindow.jsx`
     (which already has `langPref`) → `InputBar`.
   - On mic click, call `start()`. Pipe `transcript` into the existing `text` state so the user
     can edit before sending. On `onend`/final result, keep text in the box (do **not** auto-send,
     to allow correction).
   - Show a recording indicator (pulsing dot) while `listening`. Hide the mic button entirely when
     `!supported`.
3. Accessibility: `aria-label` "Speak your question", `aria-pressed={listening}`. Respect the
   existing 500-char cap (truncate transcript).
4. Localize the mic tooltip/label: add a `micLabel` key to each module under
   `ui/src/localization/` (all 9 files) and read via `STRINGS[langPref].micLabel`.

> **Indic ASR note:** Browser `webkitSpeechRecognition` supports `hi-IN`, `mr-IN`, `ta-IN`, `te-IN`,
> `bn-IN`, `kn-IN`, `ml-IN`, `pa-IN`, `en-IN`. For better accuracy, swap the hook internals later for
> **Bhashini ASR** (govt. Indic API) behind the same `useSpeechInput` interface — no UI change needed.

### 1b. Text-to-Speech (speaker on `MessageBubble.jsx` / `RecommendationCard.jsx`)

1. Create `ui/src/hooks/useSpeech.js` wrapping `window.speechSynthesis`.
   - Return `{ supported, speaking, speak(text, bcp47), stop() }`.
   - Pick a voice whose `voice.lang` startsWith the BCP47 code from `speechSynthesis.getVoices()`;
     fall back to default if none. Handle the async `voiceschanged` event.
2. In `RecommendationCard.jsx` (and the `greeting`/`question` branches of `MessageBubble.jsx`):
   - Add a 🔊 "Listen" button. On click, call `speak(text, bcp47)` using the `lang` already on the
     message (`response.lang`). Toggle to ⏹ "Stop" while `speaking`.
   - Strip markdown before speaking — reuse the inline-token logic from `Markdown.jsx` or add a small
     `stripMarkdown(text)` helper so the synth reads clean prose.
3. Auto-play option: add a per-session toggle (e.g. a header switch in `ChatWindow.jsx`) "Auto-read
   answers". When on, call `speak()` inside the `useChat` `final` handler.
4. Localize the listen label (`listenLabel`) across all 9 localization modules.

**Files touched:** `ui/src/hooks/useSpeechInput.js` (new), `ui/src/hooks/useSpeech.js` (new),
`ui/src/components/InputBar.jsx`, `ui/src/components/MessageBubble.jsx`,
`ui/src/components/RecommendationCard.jsx`, `ui/src/components/ChatWindow.jsx`,
`ui/src/localization/*.js` (9 files), `ui/src/localization/langCodes.js` (new shared map).

**Wow ★★★★★ · Effort: Medium**

---

## 2. Live "Agent Thinking" Trace

The backend already streams `phase`, `tool_call`, and `verdict` events; `useChat` currently collapses
them into a single `status` string. Surface them as an animated, multi-step timeline.

### Steps

1. **Capture phases in `useChat.js`.** Add a `steps` array to state. In the existing listeners:
   - `'phase'` → push `{ kind: 'phase', value: data.phase, t: Date.now() }` (phases: `gather`,
     `generate`, `verify`, `translate`).
   - `'tool_call'` → push `{ kind: 'tool', value: data.name }` (tools:
     `get_farmer_profile`, `fetch_latest_advisory`, `query_knowledge_base`, `translate_output`).
   - `'verdict'` → mark verify step done with `data.verdict`.
   - On `'final'`, freeze the steps onto the final message (`message.steps = steps`) so the timeline
     persists in history, then reset the working `steps`.
2. **New component `ui/src/components/AgentTrace.jsx`.**
   - Props: `steps`, `active` (bool), `langPref`.
   - Render a horizontal/vertical chip list. Reuse the existing localized labels already present in
     `ui/src/localization/*.js`: `phaseGather`, `phaseGenerate`, `phaseVerify`, `phaseTranslate`,
     and `toolGetProfile`, `toolFetchAdvisory`, `toolQueryKb`, `toolTranslate`.
   - Active step: spinner + pulse. Completed: ✓. Map each to an icon
     (📡 advisory, 🔍 knowledge base, ✅ verify, 🌐 translate).
3. **Wire into UI.** In `ChatWindow.jsx`, render `<AgentTrace>` above the typing indicator while
   `pending`. In `MessageBubble.jsx`, render a collapsed "How I got this answer" disclosure that
   expands the frozen `message.steps` for completed messages.
4. **Timing (optional flourish):** show elapsed ms per step using the `t` timestamps — reinforces
   that real tools ran (DB + vector search), not a canned reply.

**Files touched:** `ui/src/hooks/useChat.js`, `ui/src/components/AgentTrace.jsx` (new),
`ui/src/components/ChatWindow.jsx`, `ui/src/components/MessageBubble.jsx`.
No backend changes — events already exist.

**Wow ★★★★ · Effort: Low**

---

## 3. Trust & Grounding Visualization

The verifier returns `verdict` + `citations {claim: chunk_id}`, and `EvalPanel.jsx` already lazy-loads
retrieval chunks with similarity scores. Make trust visible at a glance.

### Steps

1. **Confidence meter in `RecommendationCard.jsx`.** The `VERDICT_CONFIG` badge already exists
   (PASS ✓ green / PARTIAL ⚠ amber / REJECT ✕ red). Add beneath it:
   - A compact "grounding strength" bar derived from `Object.keys(citations).length`
     (e.g. 0 sources = "unverified", 1–2 = "supported", 3+ = "well-supported").
2. **Source cards.** The citations toggle currently lists `claim → chunk_id` codes. Upgrade each row
   to a card showing the **actual chunk text + similarity** by reusing the `evaluate.js`
   (`evaluateAnswer`) retrieval payload (`data.retrieval.chunks` → `{chunk_id, similarity, text}`),
   which `EvalPanel.jsx` already fetches. Lift that fetch so the card can render the snippet inline
   instead of only inside the eval panel.
3. **PARTIAL banner.** When `verdict === 'PARTIAL'`, show a localized notice:
   *"⚠ Some advice is unverified — confirm with your local Krishi Vigyan Kendra (KVK)."*
   Add a `partialNotice` key to all 9 localization modules. (REJECT already shows the KVK fallback.)
4. **Citation provenance.** If a chunk_id maps to an IMD advisory, surface the `bulletin_date`
   from the forecast data (see feature 4) so farmers see *"Source: IMD bulletin, 18 Jun 2026."*

**Files touched:** `ui/src/components/RecommendationCard.jsx`, `ui/src/api/evaluate.js`
(expose retrieval to the card), `ui/src/localization/*.js` (9 files).

**Wow ★★★ · Effort: Low**

---

## 4. Proactive, Contextual Alerts

Shift from reactive to proactive using data already collected: the farmer profile
(`district`, `crop_variety`, `growth_stage`, `lang_pref`) + the daily IMD scrape.

### Steps

1. **Backend alert endpoint.** Add `GET /api/alerts/{farmer_id}` in `app/routes/` that:
   - Loads the `Farmer` row (district, crop_variety, growth_stage, lang_pref).
   - Reads the latest `imd_advisories` row for the district via the existing
     `forecast.py` query (`rainfall_prob`, `rainfall_category`, `min_temp_c`, `max_temp_c`,
     `advisory_text`, `bulletin_date`, `is_stale`).
   - Cross-references `CropWaterRequirement` (`water_sensitivity`, `min/optimal/max_rainfall_mm`) and
     `growth_stage` to derive rule-based alerts, e.g.:
     - `rainfall_category == 'high'` + stage `flowering/sowing` → *"Heavy rain in 48h — delay spraying/sowing."*
     - `water_sensitivity == 'high'` + low rainfall_prob → *"Dry spell — plan irrigation."*
   - Returns a list of `{severity, title, body, source: 'IMD bulletin <date>'}`, optionally translated
     to `lang_pref` via the existing `translation.py` service.
2. **Frontend "Today's advisory" card.** On `/chat` load (`ChatWindow.jsx` mount), call the new
   endpoint and render a dismissible `AlertCard` above the chat log. Reuse the verdict-badge styling
   for severity (info/warn/danger). Persist "dismissed today" in `localStorage` keyed by date.
3. **Optional push:** emit alerts as a synthetic `MessageBubble` (`type: 'greeting'`-style) so they
   feel like the agent proactively reaching out, complete with the 🔊 Listen button from feature 1.
4. **Localization:** alert templates live server-side; pass `lang_pref` so bodies arrive pre-translated
   (consistent with `AgentResponse.lang`).

**Files touched:** `app/routes/alerts.py` (new), `app/routes/__init__.py` (register),
`ui/src/api/client.js` (add `getAlerts`), `ui/src/components/AlertCard.jsx` (new),
`ui/src/components/ChatWindow.jsx`.

**Wow ★★★★ · Effort: Medium**

---

## 5. Visual Recommendation Cards

Replace text walls with glanceable visuals that cross literacy and language barriers. Numbers + icons
+ color communicate far better than paragraphs.

### Steps

1. **Water-requirement gauge.** Build `ui/src/components/WaterGauge.jsx` fed by
   `CropWaterRequirement` (`min_rainfall_mm`, `optimal_rainfall_mm`, `max_rainfall_mm`,
   `water_sensitivity`). Render a horizontal band (low → optimal → high) with a marker for the
   district's current/expected rainfall (`rainfall_prob` / historical). Add a backend field to the
   chat response or a small `GET /api/crop/{crop}/water` endpoint to expose these numbers to the UI.
2. **Rainfall sparkline.** Build `ui/src/components/RainfallSparkline.jsx` from
   `IMDHistoricalRainfall` (`year, month, rainfall_mm, normal_rainfall_mm, departure_pct`).
   - Add `GET /api/rainfall/{district}?months=12` returning the last 12 monthly points.
   - Plot actual vs. normal as a tiny inline SVG sparkline (no heavy chart lib); color the marker by
     `departure_pct` sign (deficit red / surplus blue).
3. **Sowing-window calendar strip.** Derive from `CropWaterRequirement`
   (`kharif_suitable`, `rabi_suitable`, `zaid_suitable`, `growing_duration_days`). Render a 12-month
   strip highlighting suitable sowing months for the farmer's crop and current `growth_stage`.
4. **Compose into `RecommendationCard.jsx`.** When the agent answer is about water/sowing/rainfall,
   render the relevant visual beneath the markdown text (keep text for screen readers + TTS).
   Keep visuals additive — never replace the verified text/citation path.

**Files touched:** `ui/src/components/WaterGauge.jsx` (new),
`ui/src/components/RainfallSparkline.jsx` (new), `ui/src/components/SowingCalendar.jsx` (new),
`ui/src/components/RecommendationCard.jsx`, plus small read-only backend routes for crop/rainfall data.

**Wow ★★★ · Effort: Medium**

---

## 6. Quick-Win Polish

Cheap UX lifts that compound.

### Steps

1. **Suggested-question chips.** Add a `suggestions` array (3–4 starter questions) per language to each
   `ui/src/localization/*.js` module (e.g. *"When should I sow?"*, *"How much water does my crop need?"*).
   Render as tappable chips below the greeting in `ChatWindow.jsx`; tapping calls
   `useChat.sendMessage(chip)`. Hide once the first user message is sent.
2. **Typing indicator + optimistic streaming.** `useChat` already exposes `pending`/`streaming`/`status`.
   Ensure `ChatWindow.jsx` shows an animated 3-dot indicator while `pending && !streaming`, then the
   live token bubble while `streaming` (the `type: 'streaming'` branch in `MessageBubble.jsx`).
3. **Offline / PWA.** Add `vite-plugin-pwa` to `ui/vite.config.js`:
   - Cache the app shell + last `AgentResponse` (and today's alert from feature 4) in
     `localStorage`/Cache API so a farmer with flaky connectivity sees the last advice offline.
   - Add a manifest (name, icons, theme) for "Add to Home Screen".
4. **Connection status.** Surface `socket.js` connect/disconnect as a small banner ("Reconnecting…")
   in `ChatWindow.jsx` so dropouts on rural networks are visible, not silent failures.

**Files touched:** `ui/src/localization/*.js` (9 files), `ui/src/components/ChatWindow.jsx`,
`ui/vite.config.js`, `ui/public/` (PWA icons/manifest).

**Wow ★★ · Effort: Low**

---

## Priority Ranking (wow-per-effort)

| # | Feature | Wow | Effort | Backend change? | Why |
|---|---------|-----|--------|-----------------|-----|
| 1 | Voice in/out | ★★★★★ | Medium | No (browser APIs) | Solves the literacy barrier; defines the product |
| 2 | Live agent trace | ★★★★ | Low | No (events exist) | Data already streamed; pure UI |
| 4 | Proactive alerts | ★★★★ | Medium | Yes (1 endpoint) | Scraper + profile already exist |
| 3 | Grounding / source cards | ★★★ | Low | No (reuse evaluate) | Differentiator vs. generic LLM chat |
| 5 | Visual cards | ★★★ | Medium | Yes (read-only routes) | Glanceable; beats text walls |
| 6 | Quick-win polish | ★★ | Low | No | Cheap UX lifts |

**Suggested build order:** 2 → 3 → 6 (all front-end, no backend) for fast visible wins, then 1
(voice — the standout demo feature), then 4 and 5 (need small backend endpoints).

**Single standout demo feature:** Voice-first interaction — it transforms CropCompass into something
a non-literate farmer can actually use.
