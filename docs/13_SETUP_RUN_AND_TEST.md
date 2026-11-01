# Setup, Run, and Testing Guide

> **Audience**: Developers setting up the project for the first time, DevOps engineers, and QA automation testers.  
> **Scope**: Prerequisites, environment variables, PostgreSQL database creation, starting the server, running tests, and troubleshooting.

---

## 1. System Prerequisites

Before running RECRM, verify that your development machine meets the following requirements:

- **Operating System**: Linux (Ubuntu 20.04+, Debian 11+, Fedora, Arch) or Windows WSL2.
- **Python**: Version **3.12 or higher** (Python 3.14.4 is tested and verified).
- **PostgreSQL**: Version **16 or higher** (running locally on port `5432`).
- **Web Browser**: Any modern browser (Google Chrome, Microsoft Edge, Mozilla Firefox, Apple Safari).
- **Git**: For version control.

---

## 2. Environment Setup (Step-by-Step)

### Step 1: Clone the Repository & Enter Directory
```bash
git clone <repository_url> RECRM
cd RECRM
```

### Step 2: Create Python Virtual Environment
```bash
# Create isolated virtual environment using Python 3.12+
python3 -m venv .venv

# Activate environment (optional, script can use .venv/bin/python directly)
source .venv/bin/activate
```

### Step 3: Install Required Dependencies
```bash
# Upgrade pip and install all backend and test dependencies
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### Step 4: Configure Environment Variables (`.env`)
Create a `.env` file in the root directory:

```bash
cat << 'EOF' > .env
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_NAME=re_db
EOF
```

> [!NOTE]
> Replace `your_postgres_password` with the actual password of your local PostgreSQL `postgres` user.

---

## 3. Database Initialization

### Step 1: Ensure PostgreSQL Service is Running
```bash
sudo systemctl start postgresql
sudo systemctl status postgresql
```

### Step 2: Create the `re_db` Database
```bash
# Connect to PostgreSQL and create the database if it doesn't already exist
sudo -u postgres psql -c "CREATE DATABASE re_db;"
```

### Step 3: Run the Schema & Seeding Script
RECRM includes an automated script that builds all 53 tables, 45 sequences, and seeds initial reference data (cities, roles, permissions, branches, users, and properties):

```bash
PYTHONPATH=src/backend .venv/bin/python src/backend/scripts/reset_database.py
```

Expected output:
```
✓ Connected to PostgreSQL (re_db)
✓ Dropped existing tables and sequences
✓ Created 53 tables and 45 sequences
✓ Seeded system organizations, branches, and roles
✓ Seeded reference cities, property types, and workflow SOP templates
✓ Seeded 10 system test personas (users 1 to 51)
✓ Database successfully initialized!
```

---

## 4. Starting the Server

RECRM provides a convenient bash launcher script: [`start_server.sh`](file:///home/nemro/RECRM/start_server.sh).

### Option A: Foreground Mode (Recommended for Development)
```bash
./start_server.sh
```
- Starts Uvicorn ASGI server on `http://localhost:8000`.
- Automatically opens your default web browser to `http://localhost:8000/ui/index.html`.
- Displays real-time HTTP access logs in your terminal.
- Press `Ctrl + C` to stop.

### Option B: Daemon Mode (Background Process)
```bash
./start_server.sh --daemon
```
- Starts the server in the background and writes logs to `server.log`.

### Useful Server Commands:
```bash
# Check status of PostgreSQL and RECRM server
./start_server.sh --status

# Stop running server
./start_server.sh --stop

# Restart server
./start_server.sh --restart
```

### Option C: Manual Command Line Launch
If you prefer running Uvicorn manually:
```bash
PYTHONPATH=src/backend .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 5. Verifying the Installation

### 1. Test Backend Health Check
```bash
curl http://localhost:8000/health
```
Expected response:
```json
{
  "status": "healthy",
  "service": "recrm-api",
  "version": "1.0.0",
  "database": "re_db"
}
```

### 2. Access the Interactive API Docs
Open your browser to:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### 3. Access the Frontend Dashboard
Open your browser to:
- **Unified Portal**: `http://localhost:8000/ui/index.html`

---

## 6. Running Automated Tests

RECRM has 31 test suites containing **198 automated integration tests** validating leads, matching, reservations, invoicing, cancellations, and RBAC.

### Run All 198 Tests:
```bash
PYTHONPATH=src/backend .venv/bin/pytest tests/ -v
```

Expected summary output:
```
============================= 198 passed in 14.82s =============================
```

### Run a Specific Test Suite:
```bash
# Test the end-to-end sales workflow
PYTHONPATH=src/backend .venv/bin/pytest tests/test_e2e_complete_workflow.py -v

# Test 48-hour reservation concurrency locks
PYTHONPATH=src/backend .venv/bin/pytest tests/test_sales_reservations.py -v

# Test ZATCA invoicing and fee calculations
PYTHONPATH=src/backend .venv/bin/pytest tests/test_finance_invoices.py -v

# Test gated cancellation and financial remediation
PYTHONPATH=src/backend .venv/bin/pytest tests/test_gated_cancellations.py -v
```

---

## 7. Troubleshooting & FAQ

### Issue 1: `asyncpg.exceptions.InvalidPasswordError`
- **Cause**: Password in `.env` does not match your local PostgreSQL `postgres` user password.
- **Fix**: Check or reset your PostgreSQL password:
  ```bash
  sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'your_new_password';"
  ```
  Then update `DB_PASSWORD` in your `.env` file.

### Issue 2: `ModuleNotFoundError: No module named 'app'`
- **Cause**: Python does not know where the `app` package is located.
- **Fix**: Prefix commands with `PYTHONPATH=src/backend`:
  ```bash
  PYTHONPATH=src/backend .venv/bin/python ...
  ```

### Issue 3: Port 8000 is Already in Use
- **Cause**: Another instance of Uvicorn or another web server is listening on port 8000.
- **Fix**: Run the stop command:
  ```bash
  ./start_server.sh --stop
  ```
  Or kill the process directly:
  ```bash
  fuser -k 8000/tcp
  ```

### Issue 4: PostgreSQL Connection Refused (`port 5432`)
- **Cause**: The PostgreSQL service is stopped.
- **Fix**: Start the service via systemd:
  ```bash
  sudo systemctl start postgresql
  ```

