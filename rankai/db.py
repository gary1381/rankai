"""SQLite store. raw_items and judgments are append-only; opps is the normalized view, refreshed on every ingest."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data' / 'rankai.sqlite'

SCHEMA = """
create table if not exists raw_items(
  id integer primary key, source text not null, source_id text not null, fetched_at text not null, payload text);
create index if not exists ix_raw_src on raw_items(source, source_id);

create table if not exists opps(
  id integer primary key, source text not null, source_id text not null, source_type text not null,
  url text, apply_url text, title text, org text, kind text, location text, remote real,
  salary_min real, salary_max real, currency text, period text, salary_usd_year real,
  posted_at text, tags text, text text, lang text, content_hash text, cluster_id integer,
  first_seen text, last_seen text, unique(source, source_id));
create index if not exists ix_opps_cluster on opps(cluster_id);

create virtual table if not exists opps_fts using fts5(title_tok, body_tok);

create table if not exists vecs(opp_id integer primary key, model text, content_hash text, v blob);

-- where each posting is (places.classify, 11-07): 'China/Zhejiang/Hangzhou', '*' = anywhere; no row = unknown
create table if not exists opp_places(opp_id integer not null, path text not null,
    primary key(opp_id, path)) without rowid;
create index if not exists ix_opp_places_path on opp_places(path);

create table if not exists judgments(
  id integer primary key, ts text not null, kind text not null, query text, intent text, opp_id integer,
  scores text, rationale text, judge text not null, prompt_version text not null);
create index if not exists ix_judg on judgments(kind, opp_id);

create table if not exists fetch_log(source text, ts text, n integer, ok integer, note text);

create table if not exists snapshots(name text primary key, ts text, max_opp_id integer, n integer, note text);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def connect(path: Path = DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('pragma journal_mode=wal')
    c.executescript(SCHEMA)
    return c
