# Frontend Contract — CropCompass

**Status:** Pending approval  
**Owned by:** Member 5 (Frontend & Integration)  
**Requires approval from:** Member 1 (API / Backend — task 6.1) · Member 3 (Agent loop — task 2.4)

> This document is the authoritative contract between the frontend (`ui/`) and the backend
> services. Any change to the shapes below is a **breaking contract change** and must be
> communicated to all three members before merging. The frontend mock backend (§5 of
> `PLAN_MEMBER5.md`) is generated from these fixtures, so drift will surface as E2E failures.

---

## 1. REST Endpoints

Base URL: `VITE_API_URL` (dev default: `http://localhost:8000`)

| Method | Path | Request body | Success response | Owner |
|--------|------|-------------|-----------------|-------|
| `POST` | `/api/chat` | `ChatRequest` | `AgentResponse` | Member 1 + Member 3 |
| `POST` | `/api/profile` | `FarmerCreate` | `FarmerResponse` (incl. `farmer_id`) | Member 1 |
| `GET`  | `/api/profile/{farmer_id}` | — | `FarmerResponse` | Member 1 |
| `GET`  | `/api/forecast/{district}` | — | Latest advisory object | Member 1 |
| `GET`  | `/api/districts` | — | `{ districts: string[] }` | Member 1 |

> `/api/districts` is a new endpoint requested by the frontend for onboarding dropdowns. It
> must return the complete master list of valid district names so the client can pre-filter
> before the user submits the profile form.

---

## 2. `ChatRequest` Schema

Sent as JSON body on `POST /api/chat`. This is the **HTTP fallback path** for chat; the
primary real-time path is Socket.IO (§5). The mock backend must honour both.

```jsonc
{
  "farmer_id":  "<uuid>",
  "message":    "क्या मुझे अभी बुवाई करनी चाहिए?",  // max 500 characters
  "session_id": "<sid>"                               // optional; server assigns one if omitted
}
```

Response is `AgentResponse` (§6). HTTP status `200` on success; `422` if `farmer_id` is
unknown or `message` exceeds 500 chars.

---

## 3. `FarmerCreate` Request Schema

Sent as JSON body on `POST /api/profile`.

```jsonc
{
  "district":     "Pune",
  "soil_type":    "clay_loam",        // enum: clay | loam | sandy | clay_loam | silt_loam
  "crop_variety": "Soybean JS-335",   // free text, minimum 2 characters
  "growth_stage": "sowing",           // enum: sowing | vegetative | flowering | maturity
  "lang_pref":    "hin_Deva"          // FLORES-200 code (see §7)
}
```

---

## 4. `FarmerResponse` Schema

Returned on both `POST /api/profile` and `GET /api/profile/{farmer_id}`.

```jsonc
{
  "farmer_id":    "<uuid>",
  "district":     "Pune",
  "soil_type":    "clay_loam",
  "crop_variety": "Soybean JS-335",
  "growth_stage": "sowing",
  "lang_pref":    "hin_Deva"
}
```

---

## 5. Chat Transport — Socket.IO

**Server URL:** same as `VITE_API_URL`  
**Transport:** Socket.IO (not raw WebSocket)  
**Pinned versions:** `socket.io-client@4.x` (frontend) ↔ `python-socketio@5.x` (backend)  
— version mismatch is a known integration risk; pin both sides explicitly.

### Client → Server

Event name: **`chat`**

```jsonc
{
  "farmer_id": "<uuid>",
  "message":   "अगले सप्ताह बुवाई करनी है?"
}
```

### Server → Client

Event name: **`response`**

Payload: `AgentResponse` (see §6).

---

## 6. `AgentResponse` Schema

Returned by `POST /api/chat` and emitted by the server on the `response` Socket.IO event. Owned by Member 3 (task 2.4).

```jsonc
{
  "text":       "अभी बुवाई करें...",     // already translated to farmer's lang_pref
  "lang":       "hin_Deva",              // FLORES-200 code of the response language
  "verdict":    "PASS",                  // enum: PASS | PARTIAL | REJECT
  "citations":  { "claim text": "chunk_id" },
  "session_id": "<sid>"
}
```

### Verdict semantics

| Verdict | Meaning | UI behaviour |
|---------|---------|-------------|
| `PASS` | All claims verified against RAG chunks | Show `text` + citations |
| `PARTIAL` | Some claims unverified | Show `text` with an "⚠ some advice unverified" warning + citations |
| `REJECT` | Hallucination detected — do not show raw advice | Show **only** the safe fallback message; never expose `text` |

---

## 7. FLORES-200 Language Codes

| Display label | `lang_pref` value |
|--------------|-------------------|
| हिंदी | `hin_Deva` |
| தமிழ் | `tam_Taml` |
| తెలుగు | `tel_Telu` |
| मराठी | `mar_Deva` |
| ਪੰਜਾਬੀ | `pan_Guru` |
| English | `eng_Latn` |

---

## 8. Error Handling Expectations

- `POST /api/chat` with an unknown `farmer_id` or `message` > 500 chars → `422 Unprocessable Entity`.
- `POST /api/profile` with an unknown district → `422 Unprocessable Entity`; the frontend
  surfaces this inline on Step 1 of the onboarding wizard.
- `GET /api/forecast/{district}` with no available forecast → `200` with a graceful
  degradation payload (not `404`); the frontend displays a "no forecast available" message.
- Socket connection failure → the frontend shows a reconnecting indicator and retries
  automatically (Socket.IO built-in reconnection).

---

## 9. CORS

The backend must allow the frontend origin:

- Development: `http://localhost:5173` (Vite dev server default)
- Production: the domain serving the built `ui/dist` assets

---

## Approval

| Member | Role | Approved | Date |
|--------|------|----------|------|
| Member 1 | API / Backend (tasks 1.3, 6.1) | ☐ | |
| Member 3 | Agent loop / `AgentResponse` (task 2.4) | ☐ | |
| Member 5 | Frontend (author) | ✓ | 2026-06-13 |
