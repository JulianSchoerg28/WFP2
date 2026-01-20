Frontend MVP (React + Vite)

Quick start (from project root):

1. cd frontend
2. npm install
3. npm run dev

Environment variables (optional):
- `VITE_AUTH_URL` (default: http://localhost:8002)
- `VITE_PRODUCT_URL` (default: http://localhost:8001)

Features included:
- Login / Register (stores JWT in `localStorage`)
- Product list with search and basic pagination

Notes:
- This is an MVP scaffold. For production: add HTTPS, secure token handling, refresh tokens, better error handling and styling.
