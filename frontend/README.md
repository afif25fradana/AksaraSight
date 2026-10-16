# AksaraSight Web UI Frontend

React + TypeScript + Tailwind CSS workspace interface for AksaraSight.

## Development

```bash
npm install
npm run dev
```

The dev server proxies API and health requests to the local backend at `http://127.0.0.1:8000`.

## Production Build

```bash
npm run build
```

Builds the static distribution bundle into `../web/static/` for serving by the FastAPI backend.

## Testing

```bash
npm test
```
