# Dependency Vulnerability Audit

## Beta Release scan: 2026-11-14

**Tool:** pip-audit 2.10.1 (PyPI advisory database), run with `pip-audit -r requirements.txt`.
**Scope:** the 14 packages pinned in `requirements.txt` plus the 14 packages they pull in (28 total).

### Findings

| Package | Old version | Advisory | Issue | Fixed in | Action |
|---|---|---|---|---|---|
| Werkzeug | 3.1.6 | PYSEC-2026-4312 / CVE-2026-102598 | `safe_join` / `send_from_directory` accept Windows device names such as `NUL:`, so a crafted path can hang a request on a Windows/NTFS server | 3.1.9 | Upgraded to 3.1.9 |
| pytest | 8.3.4 | PYSEC-2026-1845 / CVE-2025-71176 | Predictable `/tmp/pytest-of-{user}` folders on Linux/macOS let another local user cause a denial of service or possibly gain privileges | 9.0.3 | Upgraded to 9.0.3 |

No other package had a known vulnerability.

### Packages that could not be upgraded

None. Both vulnerable packages were upgraded.

### Verification

- `pip-audit -r requirements.txt` on the updated file: **No known vulnerabilities found.**
- Werkzeug 3.1.9 is compatible with Flask 3.1.3 (Flask needs Werkzeug >= 3.1).
- pytest 9.0.3 needs Python 3.10 or newer. The project uses Python 3.12+ (see README).
- The full test suite (`backend/tests`) was run against a fresh Postgres database with the old and the new versions. Both gave the same result: 62 passed, 3 skipped, 3 failed.
  - The 3 failures were already failing before the upgrade: `test_login_connection.py`. Those tests give the login route a fake database connection that predates the login-lockout feature, so the lockout check reads the fake account as locked and the route returns 429 "Too many failed login attempts". They need updating separately; they are not caused by the package upgrades.
  - Skipped: 1 needs AWS S3 configured, 2 need seeded wishlist data.

### How to re-run

```
venv\Scripts\python -m pip install pip-audit
venv\Scripts\pip-audit -r requirements.txt
```
