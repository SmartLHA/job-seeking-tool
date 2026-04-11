# Multi-LLM Chat — SPEC

## Concept & Vision

A daily-use web chat page where you talk to **MiniMax-M2.7**, **Gemma4:e4b**, and **GPT-5.4** simultaneously in a single conversation thread. One prompt → all 3 respond → you compare their thinking in real time. Clean, focused, no session switching.

**Feel:** Professional daily driver — fast, quiet, no visual clutter. The kind of tool you open alongside your work.

## Design Language

- **Aesthetic:** Minimal productivity tool — light theme, clean lines, calm
- **Colors:**
  - Background: `#f8f9fa`
  - User bubbles: `#4f46e5` (indigo)
  - MiniMax: `#10b981` (emerald)
  - Gemma: `#f59e0b` (amber)
  - GPT: `#6b7280` (gray-blue)
  - Error: `#ef4444`
- **Typography:** System fonts, readable sizes, clear hierarchy
- **Layout:** Single scrollable thread, input at bottom, model labels on each response

## Layout

```
┌──────────────────────────────────────┐
│  🧠 Multi-LLM Chat          [Clear] │
├──────────────────────────────────────┤
│                                      │
│  [User message]                      │
│                                      │
│  🤖 MiniMax-M2.7                     │
│  [Response from MiniMax]             │
│                                      │
│  🤖 Gemma4:e4b                       │
│  [Response from Gemma]               │
│                                      │
│  🤖 GPT-5.4                          │
│  [Response from GPT]                 │
│                                      │
├──────────────────────────────────────┤
│  [Message input...        ] [Send →] │
└──────────────────────────────────────┘
```

## Features

### Core
- Send one prompt → all 3 LLMs respond concurrently
- Each LLM has a color-coded response block
- Responses stream in as they arrive (real-time)
- Conversation persists in browser localStorage (per-session)
- Clear conversation button

### Interactions
- Enter to send, Shift+Enter for newline
- Sending shows "等待中..." placeholder per model
- Each model shows its own loading state
- If one model fails, its slot shows error — others still work
- Retry button per failed response

### Model routing
- MiniMax: via OpenClaw gateway (`http://127.0.0.1:18789`)
- Gemma: via Ollama (`http://127.0.0.1:11434`)
- GPT-5.4: via OpenAI-compatible API endpoint

## Technical

### Frontend
- Single HTML file: `viewer/multi_llm_chat.html`
- Vanilla JS, no framework dependencies
- Server-sent events (SSE) or polling for streaming responses
- localStorage for conversation persistence

### Backend
- New endpoint: `POST /api/multi-chat`
- Request: `{ "message": "...", "history": [...] }`
- Response: SSE stream — each model sends chunks as `{ model, content, done, error }`
- Concurrent LLM calls via Python threading
- OpenClaw gateway auth via token in header

### LLM endpoints
- **MiniMax**: `POST http://127.0.0.1:18789/v1/chat/completions` (gateway, needs Authorization: Bearer token)
- **Gemma**: `POST http://127.0.0.1:11434/api/chat` (Ollama, no auth)
- **GPT-5.4**: OpenAI-compatible endpoint via configured provider

## Implementation Notes

1. Start with MiniMax + Gemma (both local), GPT can be stubbed initially
2. Use `threading` for concurrent calls
3. SSE streaming to frontend for real-time feel
4. Graceful degradation — if one model fails, others still respond

## Success Criteria

- [ ] Single HTML page loads at `http://127.0.0.1:8765/viewer/multi_llm_chat.html`
- [ ] Sending a message gets responses from all 3 models
- [ ] Responses appear in real-time as they stream in
- [ ] Conversation persists on page refresh
- [ ] Clear button resets the conversation
- [ ] Failed model shows error without blocking others
