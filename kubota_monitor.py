import json, logging, os, re, time, html
from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
from telegram import send_message

ROOT=Path(__file__).resolve().parent
config=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
LOG=logging.getLogger("radar")
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
UA="Mozilla/5.0 (compatible; KubotaRadar/1.0)"

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.href=None; self.parts=[]
    def handle_starttag(self,t,a):
        if t=="a":
            d=dict(a); self.href=d.get("href"); self.parts=[]
    def handle_data(self,d):
        if self.href is not None: self.parts.append(d)
    def handle_endtag(self,t):
        if t=="a" and self.href is not None:
            self.links.append((self.href," ".join(" ".join(self.parts).split())))
            self.href=None; self.parts=[]

def norm(s): return re.sub(r"[^a-z0-9]+"," ",html.unescape(s).lower()).strip()
def model_match(text):
    t=norm(text)
    for model,terms in config["models"].items():
        for term in terms:
            n=norm(term)
            # Match model-specific number as well as configured term variants
            if n and n in t: return model
    return None

def search(site,term):
    url=site["search_url"].format(query=quote_plus(term))
    try:
        req=Request(url,headers={"User-Agent":UA,"Accept":"text/html","Accept-Language":"nl,en;q=0.8"})
        with urlopen(req,timeout=config.get("request_timeout_seconds",20)) as resp:
            page=resp.read().decode("utf-8",errors="replace")
    except Exception as e:
        LOG.warning("Bron %s, zoekterm %s: %s",site["name"],term,e); return []
    p=Parser(); p.feed(page); out=[]; domain=urlparse(site["base_url"]).netloc
    for href,title in p.links:
        if not href or href.startswith(("#","javascript:","mailto:")) or not title: continue
        full=urljoin(site["base_url"],href).split("#")[0]
        parsed=urlparse(full)
        if parsed.netloc!=domain and not parsed.netloc.endswith("."+domain): continue
        model=model_match(title) or model_match(full.replace("-"," "))
        if not model: continue
        if full in [x["url"] for x in out]: continue
        out.append({"id":full,"url":full,"title":title[:250],"site":site["name"],"model":model})
        if len(out)>=config.get("max_results_per_search",40): break
    return out

def write_feed(items):
    rss=ET.Element("rss",version="2.0"); channel=ET.SubElement(rss,"channel")
    for tag,val in [("title",config["feed_title"]),("link",config["feed_link"]),("description",config["feed_description"]),("lastBuildDate",datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000"))]:
        ET.SubElement(channel,tag).text=val
    for x in items[:200]:
        node=ET.SubElement(channel,"item")
        ET.SubElement(node,"title").text=f'[{x["model"]}] {x["title"]}'
        ET.SubElement(node,"link").text=x["url"]
        ET.SubElement(node,"guid",isPermaLink="true").text=x["id"]
        ET.SubElement(node,"description").text=f'{x["site"]} — {x["model"]}'
        ET.SubElement(node,"pubDate").text=datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.indent(rss,space="  ")
    ET.ElementTree(rss).write(ROOT/config.get("feed_file","feed.xml"),encoding="utf-8",xml_declaration=True)

def main():
    seen_path=ROOT/config.get("seen_file","seen.json")
    try: seen=set(json.loads((ROOT/seen_path).read_text()).get("seen",[]))
    except FileNotFoundError: seen=set()
    found=[]
    for site in config["sites"]:
        for terms in config["models"].values():
            for term in terms:
                found+=search(site,term)
                time.sleep(config.get("delay_between_requests_seconds",2))
    dedup={x["url"]:x for x in found}; items=list(dedup.values())
    new=[x for x in items if x["id"] not in seen]
    if not seen:
        LOG.info("Initial run: %s links geregistreerd; geen meldingen verzonden.",len(items))
    else:
        for x in new:
            send_message(f'🔎 Nieuwe Kubota-advertentie\nModel: {x["model"]}\nSite: {x["site"]}\n{x["title"]}\n{x["url"]}')
        LOG.info("%d nieuwe links",len(new))
    seen.update(x["id"] for x in items)
    (ROOT/seen_path).write_text(json.dumps({"seen":sorted(seen)[-10000:]},indent=2),encoding="utf-8")
    write_feed(items)
if __name__=="__main__": main()
