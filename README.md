# TradeMobile posts scraper (httpx + Playwright)

## Install

```sh
pip install -r requirements.txt
python -m playwright install
```
## Run
```sh
uvicorn app.main:app --reload
```
## Use
POST /scrape
  params:
    start_url (default https://trademobile.co.il/posts/)
    limit (optional)
    concurrency (default 12)
    headless (default true)

GET /download?path=...