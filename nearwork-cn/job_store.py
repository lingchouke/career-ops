"""Local job snapshots. Search and status have no network dependencies."""
import sqlite3
from contextlib import closing
from pathlib import Path

from discovery import ALL, title_cn

DB = Path(__file__).with_name("jobs.sqlite3")
CITIES = {"上海":"shanghai", "北京":"beijing", "深圳":"shenzhen", "广州":"guangzhou",
          "杭州":"hangzhou", "成都":"chengdu", "苏州":"suzhou", "香港":"hong kong",
          "南京":"nanjing", "西安":"xi'an", "天津":"tianjin", "武汉":"wuhan", "重庆":"chongqing",
          "东莞":"dongguan", "无锡":"wuxi", "厦门":"xiamen", "台北":"taipei", "新加坡":"singapore"}

def connect(path=DB):
    db = sqlite3.connect(path, timeout=15)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sources(
            source TEXT PRIMARY KEY, company TEXT NOT NULL, industry TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(
            source TEXT NOT NULL REFERENCES sources(source) ON DELETE CASCADE, id TEXT NOT NULL,
            title TEXT NOT NULL, location TEXT NOT NULL, description TEXT NOT NULL, url TEXT NOT NULL,
            keywords TEXT NOT NULL, PRIMARY KEY(source,id));
    """)
    return db


def save(db, source, rows, updated):
    key = source["type"] + ":" + source["slug"]
    with db:
        db.execute("DELETE FROM sources WHERE source=?", (key,))
        db.execute("INSERT INTO sources VALUES (?,?,?,?)", (key,source["name"],source["industry"],updated))
        db.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                       ((key, ident, title, loc, desc, url, (title+" "+title_cn(title)).casefold())
                        for ident,title,loc,desc,url in rows))


def status(path=DB):
    if not Path(path).exists():
        return 0, None, []
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        count, updated = db.execute("SELECT (SELECT count(*) FROM jobs),max(updated) FROM sources").fetchone()
        industries = [r[0] for r in db.execute("SELECT DISTINCT industry FROM sources ORDER BY industry")]
    return count, updated, industries


def search(city, industry, keywords, path=DB):
    if not Path(path).exists():
        return []
    city = city.strip().removesuffix("市").casefold()
    filters, params = [], []
    if city:
        filters.append("(instr(lower(location),?) OR instr(lower(location),?))")
        other = CITIES.get(city) or next((cn for cn,en in CITIES.items() if en==city), city)
        params.extend((city, other))
    if industry and industry != ALL:
        filters.append("industry=?")
        params.append(industry)
    for word in keywords.casefold().split():
        filters.append("(instr(keywords,?) OR instr(lower(description),?))")
        params.extend((word,word))
    sql = "SELECT title,company,location,description,url FROM jobs JOIN sources USING(source)"
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        return [dict(zip(("岗位","公司","城市","岗位要求","来源"),r)) for r in db.execute(sql,params)]
