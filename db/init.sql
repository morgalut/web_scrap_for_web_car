CREATE TABLE IF NOT EXISTS articles (
  id          BIGSERIAL PRIMARY KEY,
  url         TEXT NOT NULL UNIQUE,
  title       TEXT NOT NULL DEFAULT '',
  published   TEXT NULL,
  content     TEXT NOT NULL DEFAULT '',
  raw_html    TEXT NULL,
  scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_articles_scraped_at ON articles (scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published);

-- keep updated_at fresh on updates
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_articles_updated_at ON articles;

CREATE TRIGGER trg_articles_updated_at
BEFORE UPDATE ON articles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();