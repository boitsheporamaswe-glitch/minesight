# MineSight: predictive maintenance for mining equipment (multi-site, multi-company)

    python run.py                   # installs what it needs, trains the model, starts the server

Then open **http://localhost:8000** in your browser and choose "Create an account".
Do not double-click `static/index.html`; the page only works through the server.

Needs Python 3.8 or newer. If port 8000 is busy: `PORT=8001 python run.py` (on Windows: `set PORT=8001` first).
If installing fails, use a virtual environment: `python -m venv venv`, activate it, then `python run.py`.

## Accounts and sites
- Creating an account makes a company (organisation), its first admin, and a simulated demo site.
- Admins add sites, team members (admin or viewer) and see each site's API key.
- Every company's data is separated: a user can only reach sites in their own organisation.
- Real sensors/gateways send readings with `X-API-Key: <site key>` to `POST /ingest`.
- Simulated sites run the demo fleet. Real sites show only what you send.

## Going live checklist
- Put it behind HTTPS (for example Caddy or nginx) and set `HTTPS=1` so cookies are marked Secure.
- Set `MINESIGHT_SECRET` (long random string) instead of the auto-generated `.secret` file.
- Set `ALLOW_SIGNUP=0` once your first customers are in; add users from the Admin panel.
- Move from SQLite to PostgreSQL/TimescaleDB, and back up the database.
- Edit demo asset costs in `app.py`. Retrain with `python train.py history.csv` on real failure data.
- Known gaps: no password reset or email verification, no audit log, in-memory login throttling (single server only).
- Shift report: GET /api/report?site=ID&hours=24 returns a branded PDF (set TZ_OFFSET_HOURS for the client's timezone).

## Work orders, incidents, webhooks
- A work order is raised automatically when an asset is flagged; priority rises if it gets worse. Planners/admins assign and close them.
- Roles: admin (everything), planner (work orders + incident reports), viewer (read-only).
- Incident log for near misses, injuries and unsafe conditions. High-severity incidents also fire the webhook.
- Per-site alert webhook (https, public addresses only): JSON `{text, site, asset, level}` for Slack, Teams, Zapier, Make or a WhatsApp gateway.

## Train on a client's own history
Admin panel, live site: upload a CSV with columns `asset, ts, vib, temp, failed` (failed=1 on the row where a breakdown happened; ts as ISO dates or epoch).
- Needs at least 5 recorded failures. Whole failure cycles are held back to check accuracy; the model is only activated if it clearly beats a constant guess.
- Send live readings at the same interval as the history file (the model learns from windows of 12 readings).
- Each site keeps its own model in `models/`. `python make_sample_data.py` writes a synthetic example file.
- Behind nginx, raise the upload limit (`client_max_body_size 8m;`).

## Put it online (Docker + automatic HTTPS)
1. On a small Linux server with Docker, point a DNS A-record for your domain at the server.
2. `cp .env.example .env`, then set `DOMAIN` and a long random `MINESIGHT_SECRET`.
3. `docker compose up -d --build`. HTTPS certificates are issued automatically.
4. Open your domain and create the first account (the first account is always allowed; with `ALLOW_SIGNUP=0` nobody else can sign up, so add people from the Admin panel).
5. Daily backup: `docker compose exec app python backup.py` (cron). Data lives in `./data`.
- Health check for uptime monitors: `GET /healthz`.
- The app is installable on phones (Add to Home Screen) once served over HTTPS. Live data needs a connection.
- Admin panel shows an activity log. Everyone can export work orders, incidents, alerts and 7 days of readings as CSV.

## Password reset and two-step sign-in
- No email server needed: an admin opens Admin > Team > Reset link and shares the one-time link (valid 1 hour, works once). The token sits after the # so it never appears in server logs.
- Changing or resetting a password signs out every other session.
- Anyone can turn on two-step sign-in (authenticator app + 8 one-time recovery codes) in Account security. Codes cannot be reused. An admin can remove a colleague's two-step if their phone is lost.
- The authenticator secret is stored in the database; protect and back up `data/` accordingly.

## Fonts
Fonts (Fraunces, Instrument Sans) are bundled in `static/fonts/` under the SIL Open Font License, so the app makes no requests to Google and works on locked-down networks.
