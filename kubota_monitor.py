
import json
import logging
import re
import time
import html
from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from telegram import send_message

ROOT = Path(__file__).resolve().parent
config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

LOG = logging.getLogger("radar")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

UA = "Mozilla/5.0 (compatible; KubotaRadar/1.0)"
SEARCH_ERRORS = []


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.parts = []

    def handle_data(self, data):
        if self.href is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            title = " ".join(" ".join(self.parts).split())
            self.links.append((self.href, title))
            self.href = None
            self.parts = []


def norm(value):
    return re.sub(
        r"[^a-z0-9]+", " ",
        html.unescape(value).lower()
    ).strip()


def model_match(text):
    text = norm(text)

    for model, terms in config["models"].items():
        for term in terms:
            term = norm(term)
            if term and term in text:
                return model

    return None


def search(site, term):
    url = site["search_url"].format(
        query=quote_plus(term)
    )

    try:
        request = Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html",
                "Accept-Language": "nl,en;q=0.8"
            }
        )

        with urlopen(
            request,
            timeout=config.get("request_timeout_seconds", 20)
        ) as response:
            page = response.read().decode(
                "utf-8", errors="replace"
            )

    except Exception as error:
        message = f'{site["name"]} / "{term}": {error}'
        SEARCH_ERRORS.append(message)
        LOG.warning("Zoekopdracht mislukt: %s", message)
        return []

    parser = Parser()
    parser.feed(page)

    results = []
    domain = urlparse(site["base_url"]).netloc

    for href, title in parser.links:
        if (
            not href
            or href.startswith(("#", "javascript:", "mailto:"))
            or not title
        ):
            continue

        full_url = urljoin(
            site["base_url"], href
        ).split("#")[0]

        parsed = urlparse(full_url)

        if (
            parsed.netloc != domain
            and not parsed.netloc.endswith("." + domain)
        ):
            continue

        model = (
            model_match(title)
            or model_match(full_url.replace("-", " "))
        )

        if not model:
            continue

        if any(item["url"] == full_url for item in results):
            continue

        results.append({
            "id": full_url,
            "url": full_url,
            "title": title[:250],
            "site": site["name"],
            "model": model
        })

        if len(results) >= config.get(
            "max_results_per_search", 40
        ):
            break

    return results


def write_feed(items):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    build_date = datetime.now(
        timezone.utc
    ).strftime("%a, %d %b %Y %H:%M:%S +0000")

    for tag, value in [
        ("title", config["feed_title"]),
        ("link", config["feed_link"]),
        ("description", config["feed_description"]),
        ("lastBuildDate", build_date)
    ]:
        ET.SubElement(channel, tag).text = value

    for item in items[:200]:
        node = ET.SubElement(channel, "item")

        ET.SubElement(node, "title").text = (
            f'[{item["model"]}] {item["title"]}'
        )
        ET.SubElement(node, "link").text = item["url"]
        ET.SubElement(
            node, "guid", isPermaLink="true"
        ).text = item["id"]

        ET.SubElement(node, "description").text = (
            f'{item["site"]} — {item["model"]}'
        )
        ET.SubElement(node, "pubDate").text = build_date

    ET.indent(rss, space="  ")

    feed_path = ROOT / config.get(
        "feed_file", "feed.xml"
    )

    ET.ElementTree(rss).write(
        feed_path,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    seen_path = ROOT / config.get(
        "seen_file", "seen.json"
    )

    try:
        seen_data = json.loads(
            seen_path.read_text(encoding="utf-8")
        )
        seen = set(seen_data.get("seen", []))

    except FileNotFoundError:
        seen = set()

    found = []

    for site in config["sites"]:
        for terms in config["models"].values():
            for term in terms:
                found.extend(search(site, term))

                time.sleep(
                    config.get(
                        "delay_between_requests_seconds", 2
                    )
                )

    # Veiligheidscontrole: geen gegevens overschrijven
    # wanneer één of meer zoekopdrachten mislukten.
    if SEARCH_ERRORS:
        summary = (
            f"{len(SEARCH_ERRORS)} zoekopdracht(en) mislukt. "
            "seen.json en feed.xml blijven ongewijzigd."
        )

        LOG.error(summary)
        raise RuntimeError(summary)

    deduplicated = {
        item["url"]: item for item in found
    }

    items = list(deduplicated.values())

    new_items = [
        item for item in items
        if item["id"] not in seen
    ]

    if not seen:
        LOG.info(
            "Initial run: %s links geregistreerd; "
            "geen meldingen verzonden.",
            len(items)
        )

    else:
        for item in new_items:
            send_message(
                "🔎 Nieuwe Kubota-advertentie\n"
                f'Model: {item["model"]}\n'
                f'Site: {item["site"]}\n'
                f'{item["title"]}\n'
                f'{item["url"]}'
            )

        LOG.info("%d nieuwe links", len(new_items))

    seen.update(item["id"] for item in items)

    seen_path.write_text(
        json.dumps(
            {"seen": sorted(seen)[-10000:]},
            indent=2
        ),
        encoding="utf-8"
    )

    write_feed(items)

    LOG.info(
        "Zoekronde klaar: %d advertenties gevonden.",
        len(items)
    )


if __name__ == "__main__":
    main()
