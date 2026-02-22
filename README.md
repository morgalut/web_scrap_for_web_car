# TradeMobile posts scraper (httpx + Playwright)

## Install

```sh
pip install -r requirements.txt
python -m playwright install
```
## Run
```sh
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
## Use
POST /scrape
  params:
    start_url (default https://trademobile.co.il/posts/)
    limit (optional)
    concurrency (default 12)
    headless (default true)

GET /download?path=...



# How run all scrap for all web
```sh
curl -X POST "http://localhost:8000/scrape?all_sites=true&save_html=true&close_ads=true&delay_s=0.3&delay_jitter_s=0.2&concurrency=8"
```


### Exmplete for one web
```sh
curl -X POST "http://localhost:8000/scrape?all_sites=false&start_url=https://www.gear.co.il/%D7%A8%D7%9B%D7%91-%D7%99%D7%93-%D7%A9%D7%A0%D7%99%D7%94&close_ads=true"
```

