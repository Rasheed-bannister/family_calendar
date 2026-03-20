# Contributing

We welcome contributions! Here's how to get started.

## Development Setup

1. **Fork and clone** the repository:
   ```bash
   git clone https://github.com/<your-username>/family_calendar.git
   cd family_calendar
   ```

2. **Install dependencies** (requires [UV](https://docs.astral.sh/uv/)):
   ```bash
   uv sync --group dev
   source .venv/bin/activate
   ```

3. **Install pre-commit hooks**:
   ```bash
   uv run pre-commit install
   ```

4. **Run the app locally**:
   ```bash
   python src/main.py
   # Open http://localhost:5000
   ```
   Set `"debug": true` in `config.json` for hot reloading. A default config is created on first run.

## Workflow

1. Create a branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes, then run the tests:
   ```bash
   uv run pytest
   ```

3. Commit. Pre-commit hooks handle formatting, linting, and security checks automatically. You can also run them manually:
   ```bash
   uv run pre-commit run --all-files
   ```
   Or use the smart commit script which auto-fixes and re-stages:
   ```bash
   ./git-smart-commit.sh "your commit message"
   ```

4. Push and open a Pull Request against `main`.

## Code Quality Tools

| Tool | Purpose | Command |
|------|---------|---------|
| Black | Code formatting | `uv run black src tests` |
| isort | Import sorting | `uv run isort src tests` |
| Ruff | Linting (auto-fix) | `uv run ruff check --fix src tests` |
| MyPy | Type checking | `uv run mypy src` |
| Bandit | Security scanning | `uv run bandit -r src` |
| Radon | Complexity analysis | `uv run radon cc src --show-closures` |
| Vulture | Dead code detection | `uv run vulture src --min-confidence 80` |

## Coding Standards

- **Python**: PEP 8, type hints where practical, docstrings on public functions
- **JavaScript**: ES6 modules, component pattern (see `src/static/js/components/`)
- **UI**: Touch-friendly, no visible cursor, responsive to different screen sizes
- **Threading**: Use `google_fetch_lock` for Google API calls; keep background tasks in the thread pool
- **Tests**: Pytest, mock external APIs, organize by module in `tests/`

## Architecture at a Glance

The app is a Flask application with modular blueprints. Each feature (`calendar_app`, `chores_app`, `slideshow`, `weather_integration`, `pir_sensor`, `photo_upload`) is a self-contained package with its own routes, database, and logic. The frontend uses vanilla ES6 modules coordinated by `app.js`.

Key things to know:
- **PIR motion events** flow through gpiozero -> SSE broadcast -> frontend `registerActivity()`
- **Inactivity system** in `app.js` manages day/night dimming and slideshow activation
- **Z-index layering** is critical: slideshow at -1/-2, UI at 0+, brightness overlay at 100
- **Config** lives in `config.json` (gitignored); `config.default.json` is the tracked template

See [CLAUDE.md](CLAUDE.md) for detailed architecture documentation.
