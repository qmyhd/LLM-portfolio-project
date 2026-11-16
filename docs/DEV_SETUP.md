# Local development setup

This project should be developed locally against the same Python targets used by CI. The CI workflow runs tests on Python 3.11 and 3.12, installs runtime dependencies with `requirements.txt` constrained by `constraints.txt`, and sets `PYTHONPATH` to the repository root before running pytest.

Use Python 3.11 locally unless there is a reason to test 3.12 specifically.

## Backend setup on Windows PowerShell

From any PowerShell window:

```powershell
# Check installed Python launchers
py -0p

# Install Python 3.11 if it is missing
winget install --id Python.Python.3.11 -e

# Go to the backend repo
cd "C:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project"

# Delete the old virtual environment if it exists
if (Test-Path ".venv") {
  Remove-Item -Recurse -Force ".venv"
}

# Recreate the virtual environment with Python 3.11
py -3.11 -m venv .venv

# Activate it
.\.venv\Scripts\Activate.ps1

# If activation is blocked, run this for the current PowerShell process only, then activate again
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# Confirm the virtual environment is using Python 3.11
python --version
where python

# Install dependencies using the same runtime constraint pattern as CI, plus dev tools
python -m pip install --upgrade pip
pip install -r requirements.txt -c constraints.txt
pip install -r requirements-dev.txt -c constraints.txt
```

## Backend verification

Run these commands from the backend repository root:

```powershell
$env:PYTHONPATH = (Get-Location).Path
pytest tests/ --tb=short --maxfail=5 -v --cov=src --cov-report=term-missing --ignore=tests/validate_deployment.py -m "not openai and not integration"
ruff check src/ app/ tests/
```

If tests fail with missing environment variables, copy or restore the project `.env` file and rerun the same commands.

### Tests never reach a real database

`tests/conftest.py` replaces `DATABASE_URL`, `DATABASE_DIRECT_URL` and the `SUPABASE_*` variables with an unusable sentinel before `src.config` loads, and every engine, connection and driver path raises an error naming the test. Your `.env` database is never touched. A test that needs a database supplies its own (monkeypatch `src.db.get_sync_engine` to a SQLite engine), and mocks must patch the name the code under test imported (`app.auth.execute_sql`, not `src.db.execute_sql`). Tests marked `@pytest.mark.integration` skip the per-test guard but still see only the sentinel unless `ALLOW_REAL_DB_IN_TESTS=1` is set.

## Frontend setup on Windows PowerShell

The frontend is a separate repository. It uses Next.js and npm scripts for development, linting, and production builds.

```powershell
# Install Node if missing. Verify the version after install.
winget install --id OpenJS.NodeJS.LTS -e
node -v
npm -v

# Go to the frontend app directory
cd "C:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend"

# Refresh dependencies
npm install

# Verify lint and production build
npm run lint
npm run build
```

If `OpenJS.NodeJS.LTS` installs a newer major Node version and the frontend build behaves inconsistently, use nvm-windows to pin Node 20:

```powershell
winget install --id CoreyButler.NVMforWindows -e
nvm install 20
nvm use 20
node -v
npm -v
```

Then rerun:

```powershell
npm install
npm run lint
npm run build
```

## Starting the apps locally

Backend:

```powershell
cd "C:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path
# Start the backend using the project command you normally use, for example:
# uvicorn app.main:app --reload
```

Frontend:

```powershell
cd "C:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend"
npm run dev
```

The frontend build can pass without the backend running. Viewing the live app may still require backend URL and auth environment variables.