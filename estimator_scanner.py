#!/usr/bin/env python3
"""
Estimator & Construction Forum/Review Scanner v3
Scans estimation-relevant RSS feeds and industry blogs.
No API keys needed. Dead sources removed, new sources added.

Schedule via GitHub Actions cron.
"""

import json
import csv
import sys
import time
import re
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from html import unescape

# --- Configuration ---
# Only sources confirmed working as of 2026-09-01

RSS_FEEDS = {
    # === INDUSTRY NEWS (confirmed working) ===
    "Construction Dive": "https://www.constructiondive.com/feeds/news/",
    "For Construction Pros": "https://www.forconstructionpros.com/rss",
    "Construction Business Owner": "https://www.constructionbusinessowner.com/rss.xml",
    "AGC News": "https://www.agc.org/rss.xml",

    # === PRECONSTRUCTION & ESTIMATING (confirmed working) ===
    "ConstructConnect Blog": "https://www.constructconnect.com/blog/rss.xml",
    "Procore Jobsite Blog": "https://www.procore.com/jobsite/feed/",

    # === CONSTRUCTION TECHNOLOGY ===
    "Construction Junkie": "https://feeds.feedburner.com/ConstructionJunkie",
    "Fieldwire Blog": "https://www.fieldwire.com/blog/feed/",
    "Buildern Blog": "https://www.buildern.com/blog/feed/",
    "Levelset Blog": "https://www.levelset.com/blog/feed/",
    "eSUB Blog": "https://esub.com/blog/feed/",
    "Building Design + Construction": "https://www.bdcnetwork.com/rss.xml",

    # === WORKFORCE & LABOR ===
    "Construction Analytics": "https://edzarenski.com/feed/",
    "Associated General Contractors": "https://www.agc.org/rss.xml",

    # === MECHANICAL / PIPING / MEP ===
    "MCAA News": "https://www.mcaa.org/feed/",
    "PHCC Connect": "https://www.phccweb.org/feed/",
    "Plumbing Engineer": "https://www.plumbingengineer.com/feed/",
    "ASHRAE Journal": "https://www.ashrae.org/rss/journal",
    "Mechanical Hub": "https://mechanicalhub.com/feed/",

    # === PROJECT MANAGEMENT & BIDDING ===
    "Clearstory Blog": "https://www.clearstorydata.com/blog/feed/",
    "SmartBid Blog": "https://www.smartbidnet.com/blog/rss.xml",
    "Dodge Data Blog": "https://www.construction.com/blog/feed/",

    # === SAFETY & WORKFORCE DEVELOPMENT ===
    "NCCER Blog": "https://www.nccer.org/news/feed/",
    "OSHA QuickTakes": "https://www.osha.gov/quicktakes/feed",

    # === GULF COAST / INDUSTRIAL ===
    "Plant Services": "https://www.plantservices.com/rss/",
    "Chemical Engineering": "https://www.chemengonline.com/feed/",
    "Engineering News-Record": "https://www.enr.com/articles/feed",
}

KEYWORDS = [
    # Core estimating
    "estimat", "takeoff", "take-off", "MTO", "material takeoff",
    "quantity survey", "cost estimat", "bid manage",
    # Piping and mechanical
    "P&ID", "piping", "isometric", "pipe spool", "weld map",
    "mechanical contractor", "process piping", "ASME B31",
    # Tools and software
    "bluebeam", "planswift", "HCSS", "accubid", "fastpipe",
    "sage estimating", "procore estimating", "quoteSoft",
    "on-screen takeoff", "OST", "stack estimating",
    "McCormick", "ConstructConnect", "WenPipe",
    # Bidding and preconstruction
    "bid", "bidding", "preconstruction", "pre-construction",
    "go/no-go", "bid-hit ratio", "win rate",
    # AI and automation
    "AI takeoff", "AI estimat", "automation", "machine learning construct",
    "artificial intelligence construct",
    # Workforce
    "burnout", "shortage", "retire", "hiring estimator",
    "workforce develop", "skilled labor", "craft worker",
    "apprentice", "training program",
    # Process and accuracy
    "Excel spreadsheet", "manual takeoff", "accuracy",
    "labor hours", "man-hours", "manhours", "labor unit",
    "MCAA labor", "SMACNA",
    # Project issues
    "cost overrun", "change order", "scope creep",
    "rework", "punch list",
    # Industrial
    "turnaround", "refinery", "petrochemical", "gulf coast",
    "industrial contractor", "EPC",
    "data center", "backlog", "workforce",
    # Technology
    "software", "digital", "construction technology",
    "BIM", "digital twin", "prefab", "modular",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUTPUT_DIR = Path("output")


def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL and return the response body as text."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  [WARN] Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def clean_xml(text: str) -> str:
    """Aggressively pre-process XML to handle common RSS issues."""
    # Strip any content before the XML declaration or first tag
    xml_start = text.find("<?xml")
    if xml_start == -1:
        xml_start = text.find("<rss")
    if xml_start == -1:
        xml_start = text.find("<feed")
    if xml_start > 0:
        text = text[xml_start:]

    # Replace unescaped ampersands
    text = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', text)
    # Remove control characters except tab, newline, carriage return
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Fix common HTML entities that break XML
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&mdash;', '-')
    text = text.replace('&ndash;', '-')
    text = text.replace('&lsquo;', "'")
    text = text.replace('&rsquo;', "'")
    text = text.replace('&ldquo;', '"')
    text = text.replace('&rdquo;', '"')
    text = text.replace('&hellip;', '...')
    return text


def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    # Remove CDATA wrappers
    text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.DOTALL)
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def matches_keywords(text: str) -> list:
    """Return list of matched keyword stems (case-insensitive)."""
    text_lower = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in text_lower]


def parse_rss(xml_text: str, source_name: str) -> list:
    """Parse RSS/Atom XML and return matching items."""
    results = []
    xml_text = clean_xml(xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  [WARN] XML parse error for {source_name}: {e}", file=sys.stderr)
        return []

    namespaces = {
        "atom": "http://www.w3.org/2005/Atom",
        "dc": "http://purl.org/dc/elements/1.1/",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    # Try RSS 2.0 items
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//atom:entry", namespaces)

    for item in items:
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        content_el = item.find("content:encoded", namespaces)
        pubdate_el = item.find("pubDate")
        author_el = item.find("author")
        creator_el = item.find("dc:creator", namespaces)
        category_el = item.find("category")

        # Atom fallback
        if title_el is None:
            title_el = item.find("atom:title", namespaces)
        if link_el is None:
            link_el = item.find("atom:link", namespaces)
        if desc_el is None:
            desc_el = item.find("atom:summary", namespaces)
        if pubdate_el is None:
            pubdate_el = item.find("atom:updated", namespaces)
            if pubdate_el is None:
                pubdate_el = item.find("atom:published", namespaces)

        title = strip_html(title_el.text) if title_el is not None and title_el.text else ""
        if link_el is not None:
            link = link_el.get("href", "") or (link_el.text or "")
        else:
            link = ""
        # Prefer content:encoded for richer text matching, fall back to description
        if content_el is not None and content_el.text:
            description = strip_html(content_el.text)
        elif desc_el is not None and desc_el.text:
            description = strip_html(desc_el.text)
        else:
            description = ""
        pubdate = pubdate_el.text if pubdate_el is not None and pubdate_el.text else ""
        author = ""
        if creator_el is not None and creator_el.text:
            author = creator_el.text
        elif author_el is not None and author_el.text:
            author = author_el.text
        else:
            author = source_name
        category = strip_html(category_el.text) if category_el is not None and category_el.text else ""

        combined = f"{title} {description}"
        matched = matches_keywords(combined)

        if matched:
            results.append({
                "source": source_name,
                "title": title.strip(),
                "url": link.strip(),
                "date": pubdate.strip(),
                "author": author.strip(),
                "preview": description[:400],
                "matched_keywords": ", ".join(sorted(set(matched))),
                "category": category,
            })

    return results


def run_scan():
    """Main scan loop."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outfile = OUTPUT_DIR / f"estimator_scan_{timestamp}.csv"

    all_results = []
    working_sources = 0
    failed_sources = 0
    failed_names = []

    print(f"=== Estimator Forum Scan v3 ({timestamp}) ===\n")

    for name, feed_url in RSS_FEEDS.items():
        print(f"Scanning {name}...")
        xml_text = fetch_url(feed_url)
        if xml_text:
            items = parse_rss(xml_text, name)
            all_results.extend(items)
            print(f"  OK: {len(items)} matching items")
            working_sources += 1
        else:
            failed_sources += 1
            failed_names.append(name)
        time.sleep(1)

    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for r in all_results:
        if r["url"] and r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            deduped.append(r)
    all_results = deduped

    # Write CSV
    fieldnames = [
        "source", "title", "url", "date", "author",
        "preview", "matched_keywords", "category"
    ]
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if all_results:
            writer.writerows(all_results)

    print(f"\nWrote {len(all_results)} items to {outfile}")

    # Summary
    print(f"\n--- Scan Summary ---")
    print(f"Sources working: {working_sources}/{len(RSS_FEEDS)}")
    print(f"Sources failed: {failed_sources}/{len(RSS_FEEDS)}")
    if failed_names:
        print(f"Failed: {', '.join(failed_names)}")
    print(f"Total matching items: {len(all_results)}")
    if all_results:
        by_source = {}
        for r in all_results:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        print("\nBy source:")
        for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
            print(f"  {source}: {count}")

        # Top keywords
        kw_counts = {}
        for r in all_results:
            for kw in r["matched_keywords"].split(", "):
                kw = kw.strip()
                if kw:
                    kw_counts[kw] = kw_counts.get(kw, 0) + 1
        print("\nTop keywords:")
        for kw, count in sorted(kw_counts.items(), key=lambda x: -x[1])[:15]:
            print(f"  {kw}: {count}")

    return outfile


if __name__ == "__main__":
    run_scan()
