# MedPerplexity Frontend

A responsive React + Vite + TypeScript workspace prototype for MedPerplexity. It includes patient context, clinical query composer, result status, evidence sources, claim-support provenance, audit notes, and light/dark themes.

## Stack

- React 19, Vite, TypeScript
- Tailwind CSS 3
- shadcn/ui-compatible design conventions and reusable utility setup (`cn`); the current screen uses custom compositional components so the prototype does not require a shadcn CLI-generated registry
- Lucide icons

## Run locally

Requires Node.js 20 or newer.

```bash
npm install
npm run dev
```

Open the local URL printed by Vite.

## Demo mode and backend integration

Demo mode is enabled by default so the UI can be explored without making API calls or presenting the demo data as a real clinical assessment.

Create `.env` in the project root to connect to a running local API:

```env
VITE_DEMO_MODE=false
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Then restart Vite. The current adapter in `src/lib/api.ts` sends `POST /v1/decide` with `{ patient_id, question, conversation_id }` and expects a JSON response with a `status` field. **Verify this against your existing FastAPI request/response schema before switching demo mode off.** If the contract differs, edit only `src/lib/api.ts` to map the frontend to the current backend. This frontend does not change backend code, rules, model behavior, or clinical statuses.

Patient records in `src/App.tsx` are synthetic UI placeholders to make the workspace navigable. Replace them with the existing patient-list endpoint when the real contract is confirmed. Do not use the placeholder data for clinical decisions.

## Build check

```bash
npm run build
```

## Important safety behavior

- The UI displays the backend's returned status and does not independently approve recommendations.
- Demo mode labels the response as synthetic and makes no backend request.
- Claim support is shown as provenance/quote validation; the UI explicitly states that quote matching does not independently establish clinical entailment.
- A missing response or network error is surfaced instead of fabricated as a clinical answer.

## Structure

```text
src/
  App.tsx             Main responsive workspace
  styles.css          Design tokens, light/dark themes, responsive layout
  lib/api.ts          Demo adapter and configurable API boundary
  lib/utils.ts        Tailwind class merge helper (`cn`)
  types/clinical.ts   Typed patient and response models
```
