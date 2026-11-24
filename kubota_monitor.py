
import json
import logging
import re
import time
import html
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode
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

SEARCH_ERRORS = []


def norm(value):
    return re.sub(
        r"[^a-z0-9]+", " ",
        html.unescape(str(value or "")).lower()
    ).strip()


def model_match(text):
    text = norm(text)

    for model, terms in config["models"].items():
        for term in terms:
            term = norm(term)
            if term and term in text:
                return model

    return None



def get_listing_url(item):
    # Gebruik eerst de volledige URL die de API aanlevert
    for key in ("vipUrl", "itemUrl", "url", "link"):
        value = item.get(key)

        if isinstance(value, str) and value.startswith("https://www.2dehands.be/"):
            if "/v/" in value and not value.rstrip("/").endswith("/v"):
                return value.split("#")[0]

    # Geen volledige advertentielink gevonden:
    # geen onvolledige link meer aanmaken.
    return None



def search(term):
    params = [
        ("attributesByKey[]", "Language:nl-BE"),
        ("attributesByKey[]", "Language:fr-BE"),
        ("limit", "100"),
        ("offset", "0"),
        ("sortBy", "SORT_INDEX"),
        ("sortOrder", "DECREASING"),
        ("viewOptions", "list-view"),
        ("searchInTitleAndDescription", "true"),
        ("query", term)
    ]

    url = (
        "https://www.2dehands.be/lrp/api/search?"
        + urlencode(params)
    )

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "nl-BE,nl;q=0.9,fr-BE;q=0.8",
            "Referer": "https://www.2dehands.be/"
        }
    )

    try:
        with urlopen(
            request,
            timeout=config.get("request_timeout_seconds", 20)
        ) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        listings = data.get("listings")

        if not isinstance(listings, list):
            raise ValueError(
                "API-antwoord bevat geen geldige 'listings'-lijst"
            )

        results = []

        for item in listings:
            if not isinstance(item, dict):
                continue

            title = (
                item.get("title")
                or item.get("name")
                or item.get("description")
                or ""
            )

            description = item.get("description", "")
            combined = f"{title} {description}"

            model = model_match(combined)
            if not model:
                continue

            listing_url = get_listing_url(item)
            if not listing_url:
                continue

            results.append({
                "id": listing_url,
                "url": listing_url,
                "title": str(title)[:250],
                "site": "2dehands",
                "model": model
            })

        return results

    except Exception as error:
        message = f'2dehands / "{term}": {error}'
        SEARCH_ERRORS.append(message)
        LOG.warning("Zoekopdracht mislukt: %s", message)
        return []


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

    feed_path = ROOT / config.get("feed_file", "feed.xml")
    ET.ElementTree(rss).write(
        feed_path,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    seen_path = ROOT / config.get("seen_file", "seen.json")

    try:
        seen_data = json.loads(
            seen_path.read_text(encoding="utf-8")
        )
        seen = set(seen_data.get("seen", []))
    except FileNotFoundError:
        seen = set()

    found = []
    terms = list(dict.fromkeys(
        term
        for model_terms in config["models"].values()
        for term in model_terms
    ))

    for term in terms:
        found.extend(search(term))
        time.sleep(
            config.get("delay_between_requests_seconds", 2)
        )

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
            "Eerste run: %d links geregistreerd; "
            "geen meldingen verzonden.",
            len(items)
        )
    else:
        for item in new_items:
            send_message(
                "🔎 Nieuwe advertentie op 2dehands\n"
                f'Model: {item["model"]}\n'
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
