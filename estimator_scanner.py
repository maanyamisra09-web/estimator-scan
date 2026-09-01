#!/usr/bin/env python3
"""
Estimator & Construction Forum/Review Scanner v2
Scans estimation-relevant RSS feeds and industry blogs.
No API keys needed.

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

RSS_FEEDS = {
    # Industry news (verified working)
    "Construction Dive": "https://www.constructiondive.com/feeds/news/",
    "For Construction Pros": "https://www.forconstructionpros.com/rss",
    "ConstructConnect Blog": "https://www.constructconnect.com/blog/rss.xml",
    "Autodesk Construction Blog": "https://www.autodesk.com/blogs/construction/feed/",
    "Construction Executive": "https://www.constructionexec.com/rss",
    "Construction Business Owner": "https://www.constructionbusinessowner.com/rss.xml",

    # Eng-Tips forums (piping, mechanical, structural)
    "Eng-Tips: Piping": "https://www.eng-tips.com/rss/forum.cfm?fid=50",
    "Eng-Tips: Mechanical": "https://www.eng-tips.com/rss/forum.cfm?fid=52",
    "Eng-Tips: Structural": "https://www.eng-tips.com/rss/forum.cfm?fid=151",
    "Eng-Tips: Estimating": "https://www.eng-tips.com/rss/forum.cfm?fid=290",

    # Technology and software
    "Constructech": "https://constructech.com/feed/",
    "Trimble Viewpoint Blog": "https://www.viewpoint.com/blog/rss.xml",
    "Procore Blog": "https://www.procore.com/jobsite/feed/",

    # Workforce and labor
    "ABC Newsline": "https://www.abc.org/News-Media/Newsline/rss",
    "AGC News": "https://www.agc.org/rss.xml",

    # Estimating specific
    "RSMeans Blog": "https://www.rsmeans.com/resources/rss",
    "Bluebeam Blog": "https://www.bluebeam.com/blog/feed/",
}

KEYWORDS = [
    "estimat", "takeoff", "take-off", "MTO", "material takeoff",
    "P&ID", "piping", "isometric", "bluebeam", "planswift",
    "HCSS", "accubid", "fastpipe", "sage estimating", "procore estimating",
    "bid", "bidding", "preconstruction", "pre-construction",
    "AI takeoff", "AI estimat", "automation",
    "burnout", "shortage", "retire", "hiring estimator",
    "Excel spreadsheet", "manual takeoff", "accuracy",
    "labor hours", "man-hours", "manhours",
    "cost overrun", "change order", "scope creep",
    "turnaround", "refinery", "petrochemical", "gulf coast",
    "mechanical contractor", "industrial contractor",
    "data center", "backlog", "workforce",
    "software", "digital", "construction technology",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUTPUT_DIR = Path("output")


def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL and return the response body as text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  [WARN] Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def clean_xml(text: str) -> str:
    """Pre-process XML to handle common malformed RSS issues."""
    # Replace unescaped ampersands (common in Eng-Tips and other forums)
    text = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', text)
    # Remove control characters except tab, newline, carriage return
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text


def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
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

    # Handle both RSS 2.0 and Atom
    namespaces = {"atom": "http://www.w3.org/2005/Atom"}

    # Try RSS 2.0 items
    items = root.findall(".//item")
    # Try Atom entries if no RSS items
    if not items:
        items = root.findall(".//atom:entry", namespaces)

    for item in items:
        # RSS 2.0
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pubdate_el = item.find("pubDate")
        author_el = item.find("author")
        creator_el = item.find("{http://purl.org/dc/elements/1.1/}creator")
        category_el = item.find("category")

        # Atom fallback
        if title_el is None:
            title_el = item.find("atom:title", namespaces)
        if link_el is None:
            link_el = item.find("atom:link", namespaces)
        if desc_el is None:
            desc_el = item.find("atom:summary", namespaces)
            if desc_el is None:
                desc_el = item.find("atom:content", namespaces)
        if pubdate_el is None:
            pubdate_el = item.find("atom:updated", namespaces)

        title = title_el.text if title_el is not None and title_el.text else ""
        if link_el is not None:
            link = link_el.get("href", "") or (link_el.text or "")
        else:
            link = ""
        description = strip_html(desc_el.text if desc_el is not None and desc_el.text else "")
        pubdate = pubdate_el.text if pubdate_el is not None and pubdate_el.text else ""
        author = ""
        if author_el is not None and author_el.text:
            author = author_el.text
        elif creator_el is not None and creator_el.text:
            author = creator_el.text
        else:
            author = source_name
        category = category_el.text if category_el is not None and category_el.text else ""

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

    print(f"=== Estimator Forum Scan ({timestamp}) ===\n")

    for name, feed_url in RSS_FEEDS.items():
        print(f"Scanning {name}...")
        xml_text = fetch_url(feed_url)
        if xml_text:
            items = parse_rss(xml_text, name)
            all_results.extend(items)
            print(f"  Found {len(items)} matching items")
            working_sources += 1
        else:
            failed_sources += 1
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
    print(f"Total matching items: {len(all_results)}")
    if all_results:
        by_source = {}
        for r in all_results:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
            print(f"  {source}: {count}")

    return outfile


if __name__ == "__main__":
    run_scan()
