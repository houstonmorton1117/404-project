# The Vault — Campus Marketplace

**A cloud-based fashion marketplace for Hampton University students**

The Vault lets student brand owners create storefronts, publish clothing listings, and manage inventory, while other students browse, wishlist, and buy items. Checkout uses an in-person exchange model, so no payments are processed.

---

## Our team

| Name |
|---|
| Obi Achebe |
| Kyren Calvin |
| Saffie Cherif |
| Danovan Golding |
| Joshua Hall |
| Jasmine Mark |
| Houston Morton |
| Rochele Solmon |

The Vault was originally designed and built for CSC 405 (Spring 2026) by David Jackson, Elali McNair, Day Ekoi, Ryan Grimes, Kaila Roberts, and Madison Boyd.

---

## Run it on your computer

This takes about 15 minutes the first time. You'll install Python and PostgreSQL, download the code, and point the app at a database on your own computer.

Follow the steps for your operating system. The commands go in a terminal. On a Mac, use the **Terminal** app. On Windows, use **PowerShell**. In VS Code, you can use **Terminal → New Terminal** on either.

### Mac

**1. Install Python 3.12 and PostgreSQL.** This uses [Homebrew](https://brew.sh). If `brew` isn't found, install Homebrew first.

```bash
brew install python@3.12 postgresql@16
brew services start postgresql@16
```

**2. Create the database**

```bash
/opt/homebrew/opt/postgresql@16/bin/createdb vault
```

**3. Download the code**

```bash
git clone https://github.com/houstonmorton1117/404-project.git
cd 404-project
```

**4. Install the app's Python packages**

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
```

**5. Create a file named `.env`** in the `404-project` folder, containing:

```
DB_HOST=localhost
DB_NAME=vault
DB_USER=your-mac-username
DB_PASSWORD=
DB_PORT=5432
SECRET_KEY=dev
```

Replace `your-mac-username` with the output of the `whoami` command. Leave `DB_PASSWORD` empty.

**6. Create the tables and start the app**

```bash
./venv/bin/python backend/init_db.py
./venv/bin/python app.py
```

Open **http://127.0.0.1:5000** in your browser. To stop the app, press **Ctrl+C** in the terminal.

### Windows

**1. Install Python 3.12** from [python.org/downloads](https://www.python.org/downloads/). On the first screen of the installer, check **"Add python.exe to PATH"**.

**2. Install PostgreSQL 16** from [postgresql.org/download/windows](https://www.postgresql.org/download/windows/). Keep the default settings. When it asks for a password for the `postgres` user, choose one and write it down, because you'll need it in step 6.

**3. Create the database.** Enter the password from step 2 when asked.

```powershell
& "C:\Program Files\PostgreSQL\16\bin\createdb.exe" -U postgres vault
```

**4. Download the code**

```powershell
git clone https://github.com/houstonmorton1117/404-project.git
cd 404-project
```

If `git` isn't found, install it from [git-scm.com](https://git-scm.com/download/win) and open a new terminal.

**5. Install the app's Python packages**

```powershell
py -3.12 -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```

**6. Create a file named `.env`** in the `404-project` folder, containing:

```
DB_HOST=localhost
DB_NAME=vault
DB_USER=postgres
DB_PASSWORD=the-password-from-step-2
DB_PORT=5432
SECRET_KEY=dev
```

**7. Create the tables and start the app**

```powershell
venv\Scripts\python backend\init_db.py
venv\Scripts\python app.py
```

Open **http://127.0.0.1:5000** in your browser. To stop the app, press **Ctrl+C** in the terminal.

### After setup

- **Starting the app next time:** open a terminal in the `404-project` folder and run only the last command: `./venv/bin/python app.py` on Mac, or `venv\Scripts\python app.py` on Windows. The database keeps its data between runs.
- **Signing up** only accepts emails ending in `@hamptonu.edu` or `@my.hamptonu.edu`. Nothing is emailed, so any made-up address at those domains works for testing.
- **Each person has their own database.** Accounts and listings you create exist only on your computer.
- **Don't use `.env.example`.** It's out of date. Use the `.env` contents above.
- **Image uploads** (listing photos, store logos, return photos) need an Amazon S3 bucket and keys, so they don't work locally yet. Everything else does.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `connection refused` or `could not connect to server` | PostgreSQL isn't running. Mac: `brew services start postgresql@16`. Windows: open **Services**, find **postgresql-x64-16**, and click **Start**. |
| `role "..." does not exist` | `DB_USER` in `.env` is wrong. Mac: use the output of `whoami`. Windows: use `postgres`. |
| `password authentication failed` | `DB_PASSWORD` in `.env` doesn't match the password you set when installing PostgreSQL (Windows). |
| `database "vault" does not exist` | Redo the create-the-database step. |
| `Address already in use` / port 5000 is busy (Mac) | macOS AirPlay Receiver uses port 5000. Turn it off in **System Settings → General → AirDrop & Handoff**, or run `./venv/bin/flask --app app run --port 5001 --debug` and open http://127.0.0.1:5001 instead. |
| `ModuleNotFoundError` | The packages aren't installed, or you ran `python` instead of the one in `venv`. Redo the install-packages step and use the `./venv/bin/python` (Mac) or `venv\Scripts\python` (Windows) commands shown above. |
| `py` or `python` not found (Windows) | Python isn't on PATH. Reinstall Python and check **"Add python.exe to PATH"**, then open a new terminal. |
| Image upload fails | Expected without S3 keys. |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask |
| Frontend | HTML, CSS, JavaScript |
| Database | PostgreSQL |
| Image storage | Amazon S3 |
| Database adapter | psycopg2 |
