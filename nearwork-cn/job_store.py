"""Local job snapshots. Search and status have no network dependencies."""
import sqlite3
import json
from extraction import schema, extract_row, LEVELS
import re
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path

from discovery import ALL, title_cn

DB = Path(__file__).with_name("jobs.sqlite3")
CITIES = {"上海":"shanghai", "北京":"beijing", "深圳":"shenzhen", "广州":"guangzhou",
          "杭州":"hangzhou", "成都":"chengdu", "苏州":"suzhou", "香港":"hong kong",
          "南京":"nanjing", "西安":"xi'an", "天津":"tianjin", "武汉":"wuhan", "重庆":"chongqing",
          "东莞":"dongguan", "无锡":"wuxi", "厦门":"xiamen", "台北":"taipei", "新加坡":"singapore"}

ANY_CITY = "不限"
UNKNOWN_CITY = "未注明城市"
CITY_NAMES = {en: cn for cn, en in CITIES.items()}
CITY_NAMES.update({"san jose":"圣何塞", "san francisco":"旧金山", "los angeles":"洛杉矶",
                  "zurich":"苏黎世", "zürich":"苏黎世", "barcelona":"巴塞罗那",
                  "toronto":"多伦多", "vancouver":"温哥华", "bengaluru":"班加罗尔",
                  "manila":"马尼拉", "berlin":"柏林", "lisbon":"里斯本", "stuttgart":"斯图加特",
                  "tel aviv-yafo":"特拉维夫", "tampa":"坦帕", "ahmedabad":"艾哈迈达巴德",
                  "aachen":"亚琛", "woburn":"沃本", "mumbai":"孟买", "mexico city":"墨西哥城",
                  "madrid":"马德里", "irvine":"尔湾", "hyderabad":"海得拉巴",
                  "ho chi minh city":"胡志明市", "dubai":"迪拜", "bogota colombia":"波哥大"})
REGIONS = {"us","usa","uk","united states","united kingdom","canada","china","中国","全国",
           "germany","israel","india","multiple locations","rust belt","research triangle park",
           "europe","emea","apac","worldwide","global","anywhere","remote","远程","不限",
           "france","japan","switzerland","spain","australia","brazil","mexico","netherlands",
           "portugal","philippines","south korea","taiwan","united arab emirates","vietnam"}

@lru_cache(maxsize=4096)
def location_cities(location):
    """One posting may name several cities or only a country, region or work arrangement."""
    names = set()
    location = re.sub(r"\b(?:on[- ]?site|hybrid|remote)\s*/\s*(?:on[- ]?site|hybrid|remote)\b",
                      " ", location, flags=re.I)
    for part in re.split(r"[/;；、|\n]", location):
        # Metro area followed by the specific office, e.g. Greater Boston (Woburn, MA).
        office = re.search(r"^\s*Greater [^(]+\(([^,()]+),", part, re.I)
        pieces = [piece.strip() for piece in re.split(r"[,，]",part)]
        name = office[1] if office else pieces[0]
        if not office:
            for piece in pieces[1:]:
                if piece.casefold() in CITY_NAMES:
                    names.add(CITY_NAMES[piece.casefold()])
                elif piece.removesuffix("市") in CITIES:
                    names.add(piece.removesuffix("市"))
        name = re.sub(r"\s*\((?:onsite|on-site|hybrid|remote)\)|\s+[-–]\s+(?:remote|hybrid|on-site).*$",
                      "", name, flags=re.I).strip()
        if name not in CITY_NAMES.values():
            name = name.removesuffix("市")
        key = re.sub(r"\s+shi$", "", name.casefold())
        if not key or key in REGIONS or re.search(r"(?: district| qu| province| region|省)$",key):
            continue
        names.add(CITY_NAMES.get(key, name.title() if name.isascii() else name))
    return frozenset(names or {UNKNOWN_CITY})

@dataclass
class LibraryStats:
    total: int
    updated: str | None
    industries: list
    companies: dict
    cities: dict
    industries_by_city: dict
    company_counts: dict

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
    schema(db)
    return db


def save(db, source, rows, updated):
    key = source["type"] + ":" + source["slug"]
    with db:
        db.execute("DELETE FROM sources WHERE source=?", (key,))
        db.execute("INSERT INTO sources VALUES (?,?,?,?)", (key,source["name"],source["industry"],updated))
        db.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                       ((key, ident, title, loc, desc, url, (title+" "+title_cn(title)).casefold())
                        for ident,title,loc,desc,url,*extra in rows))

        db.execute("INSERT OR REPLACE INTO ownership VALUES (?,?,?)",(key,source.get("domestic"),source.get("foreign_form")))
        for ident,title,loc,desc,url,*extra in rows:
            extract_row(db,key,ident,desc,extra[0] if extra else None)
        db.execute("DELETE FROM extracted WHERE source=? AND id NOT IN (SELECT id FROM jobs WHERE source=?)",(key,key))

def company_form(place,domestic,foreign):
    if not place or place.strip().casefold() in {"remote","anywhere","global","worldwide","multiple locations","远程","不限","全球"}:
        return None
    local=bool(location_cities(place) & (set(CITIES)-{"新加坡"})) or re.search(r"\bchina\b|中国",place,re.I)
    return domestic if local else foreign

def matches(row,filters):
    if not filters: return True
    if filters.get("ownership") and filters["ownership"]!=(row["性质"] or "未写明"): return False
    for field in ("years","degree","salary","languages"):
        value=row[field]
        if field in filters.get("only",()):
            if value is not None: return False
            continue
        if value is None:
            if not filters.get("unknown",True): return False
            continue
        if field=="years" and filters.get("years") is not None and value>filters["years"]: return False
        if field=="degree" and filters.get("degree") and LEVELS[value]>LEVELS[filters["degree"]]: return False
        if field=="salary":
            for bound,key in (("low","cny_max"),("high","cny_min")):
                amount=filters.get(bound)
                if amount is not None and (value[key] is None or (value[key]<amount if bound=="low" else value[key]>amount)): return False
        if field=="languages" and filters.get("language") and not any(filters["language"].casefold() in (v["language"]+" "+(v["level"] or "")).casefold() for v in value): return False
    return True


def library_stats(path=DB):
    if not Path(path).exists():
        return LibraryStats(0,None,[],{}, {},{},{})
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("BEGIN")
        updated, = db.execute("SELECT max(updated) FROM sources").fetchone()
        industries = [r[0] for r in db.execute("SELECT DISTINCT industry FROM sources ORDER BY industry")]
        companies = dict(db.execute("""SELECT company,count(jobs.id) AS n FROM sources
                    LEFT JOIN jobs USING(source) GROUP BY company ORDER BY n DESC, company"""))
        cities = Counter()
        industries_by_city = {ANY_CITY: Counter()}
        employers = {}
        for location, industry, company, count in db.execute("""SELECT location,industry,company,count(*) FROM jobs
                JOIN sources USING(source) GROUP BY location,industry,company"""):
            for name in location_cities(location) | {ANY_CITY}:
                if name != ANY_CITY:
                    cities[name] += count
                industries_by_city.setdefault(name,Counter())[industry] += count
                employers.setdefault((name,industry),set()).add(company)
                employers.setdefault((name,ALL),set()).add(company)
    ordered = dict(sorted(cities.items(),key=lambda pair:(pair[0]==UNKNOWN_CITY,-pair[1],pair[0])))
    company_counts = {key:len(names) for key,names in employers.items()}
    return LibraryStats(sum(companies.values()),updated,industries,companies,ordered,industries_by_city,company_counts)

def status(path=DB):
    stats = library_stats(path)
    return stats.total, stats.updated, stats.industries


def search_filter(city, industry, keywords):
    city = city.strip()
    if city != UNKNOWN_CITY and city not in CITY_NAMES.values():
        city = city.removesuffix("市")
    filters, params = [], []
    if city and city != ANY_CITY:
        filters.append("in_city(location, ?)")
        params.append(CITY_NAMES.get(city.casefold(),city).casefold())
    if industry and industry != ALL:
        filters.append("industry=?")
        params.append(industry)
    for word in keywords.casefold().split():
        filters.append("(instr(keywords,?) OR instr(lower(description),?))")
        params.extend((word,word))
    sql = " FROM jobs JOIN sources USING(source)"
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    return sql, params


def open_search_db(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
    db.create_function("in_city",2,lambda place, target:
                       any(name.casefold()==target for name in location_cities(place)))
    return db


def search(city, industry, keywords, path=DB, filters=None):
    if not Path(path).exists():
        return []
    suffix,params=search_filter(city,industry,keywords)
    with closing(open_search_db(path)) as db:
        where=suffix.partition(" WHERE ")[2]
        sql="""SELECT title,company,location,description,url,years,degree,salary,languages,domestic,foreign_form
               FROM jobs JOIN sources USING(source) LEFT JOIN extracted USING(source,id) LEFT JOIN ownership USING(source)"""
        rows=db.execute(sql+(" WHERE "+where if where else ""),params)
        result=[]
        for values in rows:
            row=dict(zip(("岗位","公司","城市","岗位要求","来源","years","degree","salary","languages"),values))
            row["性质"]=company_form(row["城市"],*values[-2:])
            for field in ("salary","languages"):
                if row[field]: row[field]=json.loads(row[field])
            if matches(row,filters): result.append(row)
        return result


def broader_searches(city, industry, keywords, path=DB, filters=None):
    """Offer the smallest changes that yield results, counted against one local snapshot."""
    if not Path(path).exists():
        return 0, []
    advanced=filters
    original=(city,industry,keywords)
    defaults=(ANY_CITY,ALL,"")
    captions=("不限城市","不限公司类型","不限岗位关键词")
    active=[i for i in (0,2,1) if original[i] and original[i]!=defaults[i]]
    with closing(open_search_db(path)) as db:
        db.execute("BEGIN")
        total,=db.execute("SELECT count(*) FROM jobs").fetchone()
        options=[]
        if total:
            for size in range(1,len(active)+1):
                for relaxed in combinations(active,size):
                    filters=tuple(defaults[i] if i in relaxed else value for i,value in enumerate(original))
                    suffix,params=search_filter(*filters)
                    count,=db.execute("SELECT count(*)"+suffix,params).fetchone()
                    if advanced:
                        count=len(search(*filters,path,filters=advanced))
                    if count:
                        caption="、".join(captions[i] for i in relaxed)
                        if 0 not in relaxed and city and city!=ANY_CITY:
                            caption+="在"+city
                        options.append((f"{caption}有 {count} 个岗位",filters))
                if options:
                    break
    return total,options
