# Shortlink

A small URL-shortening service with a web interface, a FastAPI JSON API, SQLite storage, optional custom aliases/expiry, and click statistics.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000.

## API

- `POST /links` — JSON body: `{"url":"https://example.com","alias":"optional","expires_at":"2027-01-01T00:00:00Z"}`. `alias` and `expires_at` are optional.
- `GET /{code}` — redirects to the destination, tracks the click, and returns 404 for an unknown code or 410 for an expired link.
- `GET /links/{code}/stats` — returns `total_clicks` and `last_clicked_at`.
- `GET /docs` — interactive API documentation.

SQLite data is stored in `links.db` by default. Set `LINKS_DATABASE` to use a different database file.

## Tests

```powershell
python -m pytest -q
```
