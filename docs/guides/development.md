# Development and contributing

How to run the backend and frontend locally, lint, type-check, test, and submit changes.

## Development Setup

### Prerequisites

- **Docker** (for the full stack) or:
- **Python 3.12+** and **Node.js 22+** (for local development)

### Backend (local)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run with auto-reload (requires a running mail server or mock)
uvicorn app.main:app --reload --port 8000
```

### Frontend (local)

```bash
cd frontend
npm install
npm run dev          # Starts Vite dev server on :3000
                     # Proxies /api/* to localhost:8000
```

### Linting & Type Checking

```bash
# Backend
cd backend
ruff check .         # Linting
ruff format .        # Formatting
mypy .               # Type checking

# Frontend
cd frontend
npm run lint         # ESLint
npm run typecheck    # TypeScript
```

### Documentation

If you edit or add any `.md` guides in the `docs/guides/` directory, you should regenerate the static HTML pages by running the build script in the root directory:

```bash
python3 scripts/build_docs.py
```

This compiles the Markdown guides into search-engine-crawlable HTML files with syntax highlighting, responsive styling, and auto-generated `sitemap.xml`/`robots.txt` files.


### Running Tests

```bash
cd backend
pytest               # Runs async tests with pytest-asyncio
```

## Contributing

Contributions are welcome. Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the linters, type checks, and tests from [Development Setup](#development-setup), backend (`ruff`, `mypy`, `pytest`) and frontend (`npm run lint`, `npm run typecheck`) must all pass
5. Commit your changes (`git commit -m "Add my feature"`)
6. Push to your fork (`git push origin feature/my-feature`)
7. Open a Pull Request

### Development Principles

- Backend code uses strict typing (`mypy --strict`) and follows the Ruff linter rules.
- Frontend code is TypeScript-first with ESLint enforced.
- All API endpoints follow RESTful conventions and return consistent JSON error envelopes.
- New features should include appropriate SSE events for real-time UI updates.
