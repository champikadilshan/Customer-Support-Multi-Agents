# Customer Support Frontend

Lean chat UI built from [shadcn-chatbot-kit](https://github.com/blazity/shadcn-chatbot-kit) components, wired to the multi-agent backend.

## What's included

- Chat message list with markdown rendering
- Streaming responses from `POST /chat/stream`
- Intent/agent routing badge
- Tool-call indicators
- Complaint HITL approval dialog
- Support-specific prompt suggestions

## Removed from the template

- Demo/docs monorepo site
- Vercel AI SDK / Groq integration
- Model picker
- File attachments
- Voice input / transcription
- Thumbs up/down ratings
- Generic weather/math demo prompts

## Setup

```bash
cd Frontend
cp .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

Make sure the backend services are running (at minimum the intent detector on port 8001, and complaint agent on 8003 for HITL flows).

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `BACKEND_URL` | `http://localhost:8001` | Intent detector orchestrator |
| `COMPLAINT_AGENT_URL` | `http://localhost:8003` | HITL resume endpoint |

The Next.js API routes proxy SSE to the backend to avoid browser CORS issues.
