# AksaraSight Web UI Frontend

React + TypeScript + Tailwind CSS workspace interface for AksaraSight.

## Prerequisites

- Node.js >= 20.0.0 (Node 22 LTS recommended)
- npm >= 9.0.0

## Development

Start the backend in development mode (allows Vite dev server origins):

```bash
# In repository root
python -m web --dev
```

Then start the Vite dev server:

```bash
# In frontend/
npm install
npm run dev
```

The dev server proxies API and health requests to the local backend at `http://127.0.0.1:8000`.

## Production Build

```bash
npm run build
```

Builds the static distribution bundle into `../web/static/` for serving by the FastAPI backend.

## Testing & Type Checking

```bash
# Run Vitest test suite
npm test

# Run TypeScript type check
npm run lint
```
