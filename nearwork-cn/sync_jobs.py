"""Update configured public job boards: python sync_jobs.py [--config FILE] [--db FILE]."""
import argparse
import html
import json
import re
from contextlib import closing
from datetime import datetime
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path

from job_store import DB, connect, save
from nearwork import get_json

CONFIG = Path(__file__).with_name("companies.json")
PAGE = 25


def companies(path=CONFIG):
    rows = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(rows,list):
        raise ValueError("公司清单应为列表")
    seen = set()
    for row in rows:
        if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k].strip()
                                           for k in ("type","slug","name","industry")):
            raise ValueError("公司信息不完整")
        key = (row["type"],row["slug"])
        if (key[0] not in ("greenhouse","lever") or not re.fullmatch(r"[a-zA-Z0-9_-]+",key[1])
                or key in seen or row.get("region","global") not in ("eu","global")):
            raise ValueError("公司来源或标识有误，或公司重复")
        seen.add(key)
    return rows


class PlainText(HTMLParser):
    blocks = {"li","p","br","div","ul","ol","section","h1","h2","h3","h4","h5","tr"}
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in self.blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        self.handle_starttag(tag, ())


def plain(markup):
    parser = PlainText()
    parser.feed(markup or "")
    parser.close()
    return "\n".join(s.strip() for s in "".join(parser.parts).splitlines() if s.strip())


def lever_text(row):
    def field(name):
        return row.get(name+"Plain") or plain(row.get(name))
    parts = [field("description") or "\n".join(filter(None,(field("opening"),field("descriptionBody"))))]
    for section in row.get("lists") or []:
        parts.extend((section.get("text"), plain(section.get("content"))))
    parts.extend((field("additional"), field("salaryDescription")))
    return "\n".join(filter(None,parts))


def fetch(source, request=get_json):
    slug = source["slug"]
    if source["type"] == "greenhouse":
        data = request(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", {"content":"true"})
        rows = data["jobs"]
        if not isinstance(rows,list) or (data.get("meta") or {}).get("total",len(rows)) != len(rows):
            raise ValueError("岗位列表不完整")
        for row in rows:
            markup = row["content"]
            if not re.search(r"<[a-zA-Z][^>]*>",markup) and "&lt;" in markup:
                markup = html.unescape(markup)
            yield (row["id"],row["title"],(row.get("location") or {}).get("name") or "",
                   plain(markup),row["absolute_url"])
    else:
        host = "api.eu.lever.co" if source.get("region")=="eu" else "api.lever.co"
        offset, seen = 0, set()
        while True:
            rows = request(f"https://{host}/v0/postings/{slug}", {"mode":"json","skip":offset,"limit":PAGE})
            if not isinstance(rows,list):
                raise ValueError("未收到岗位列表")
            if not rows:
                break
            for row in rows:
                key = row["id"]
                if key in seen:
                    raise ValueError("岗位分页重复")
                seen.add(key)
                cat = row.get("categories") or {}
                loc = [cat.get("location")] + (cat.get("allLocations") or [])
                yield key,row["text"]," / ".join(dict.fromkeys(filter(None,loc))),lever_text(row),row["hostedUrl"]
            offset += len(rows)
            if len(rows) < PAGE:
                break


def synchronize(config=CONFIG, path=DB, request=get_json):
    sources = companies(config)
    updated, failed = {}, {}
    with closing(connect(path)) as db:
        for source in sources:
            try:
                rows = list(fetch(source,request))
                ids = set()
                for ident,title,location,desc,url in rows:
                    if not ident or ident in ids or not title.strip() or not url.startswith("https://"):
                        raise ValueError("岗位信息不完整")
                    ids.add(ident)
            except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError) as exc:
                failed[source["name"]] = str(exc)
                continue
            save(db,source,rows,datetime.now().astimezone().isoformat(timespec="minutes"))
            updated[source["name"]] = len(rows)
        # Remove companies deliberately dropped from the config. Failed configured boards stay intact.
        keep = {s["type"]+":"+s["slug"] for s in sources}
        with db:
            db.executemany("DELETE FROM sources WHERE source=?",
                           [(k,) for k, in db.execute("SELECT source FROM sources") if k not in keep])
    return updated, failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="下载公开岗位到本机")
    parser.add_argument("--config", default=CONFIG)
    parser.add_argument("--db", default=DB)
    args = parser.parse_args()
    updated, failed = synchronize(args.config,args.db)
    for name, count in updated.items():
        print(f"{name}：已更新 {count} 个岗位")
    for name, error in failed.items():
        print(f"{name}：未更新，保留原有岗位。{error}")
    raise SystemExit(1 if failed else 0)
