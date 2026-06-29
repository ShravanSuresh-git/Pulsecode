# PulseCode

PulseCode is a local-first software evolution time machine. It analyzes a single Git repository, builds chronological architecture snapshots, and visualizes how files, dependencies, coupling, churn, and structural shift events evolve over time.

## Stack

- Backend: Python 3.11+, FastAPI, GitPython, NetworkX, Pandas
- Frontend: Next.js, TypeScript, Tailwind CSS, D3, Recharts

## Run Locally

Install backend dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Start the API:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Install frontend dependencies and start the app:

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## API

- `POST /analyze` with `{ "repo_path": "/path/to/local/repo", "snapshot_size": 8 }`
- `GET /timeline/{repo_id}`
- `GET /snapshot/{repo_id}/{index}`
- `GET /events/{repo_id}`
- `GET /health/{repo_id}`

