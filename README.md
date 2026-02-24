

# TradeMobile Scraper

(httpx + Playwright + PostgreSQL)

---

## Install

```bash
pip install -r requirements.txt
python -m playwright install
pip install psycopg2-binary python-dotenv
```

---

## Database (Docker)

Start Postgres + pgAdmin:

```bash
docker compose up -d
```

pgAdmin:

```
http://localhost:5050
```

---

## .env File

Create `.env` in project root:

```env
POSTGRES_DB=webcar
POSTGRES_USER=webcar
POSTGRES_PASSWORD=webcar_password

DATABASE_URL=postgresql://webcar:webcar_password@localhost:5432/webcar
```

---

## Run API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 
```

---

## Health Check

```
GET /health
```

---

## Scrape All Sites

```bash
curl -X POST "http://localhost:8000/scrape?all_sites=true&save_db=true"
```

---

## Scrape One Site

```bash
curl -X POST "http://localhost:8000/scrape?all_sites=false&start_url=https://carwiz.co.il/magazine&save_db=true"
```

---

## Optional Parameters

* `save_db=true` → save to PostgreSQL
* `save_csv=true` → save CSV
* `save_html=true` → save raw HTML
* `concurrency=8` → async workers
* `delay_s=0.3` → request delay

---
