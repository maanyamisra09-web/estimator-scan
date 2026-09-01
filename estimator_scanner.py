#!/usr/bin/env python3
"""
Estimator & Construction Forum/Review Scanner v4
Only confirmed-working RSS sources. Crash-proof fetch.
No API keys needed.
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

# --- ONLY CONFIRMED WORKING SOURCES ---
RSS_FEEDS = {
    # Industry news
    "Construction Dive": "https://www.constructiondive.com/feeds/news/",
    "For Construction Pros": "https://www.forconstructionpros.com/rss",
    "Construction Business Owner": "https://www.constructionbusinessowner.com/rss.xml",
    "AGC News": "https://www.agc.org/rss.xml",

    # Preconstruction and estimating
    "ConstructConnect Blog": "https://www.constructconnect.com/blog/rss.xml",
    "Procore Jobsite Blog": "https://www.procore.com/jobsite/feed/",

    # Mechanical, piping, MEP trade associations
    "MCAA News": "https://www.mcaa.org/feed/",
    "PHCC Connect": "https://www.phccweb.org/feed/",

    # Industrial and Gulf Coast
    "Plant Services": "https://www.plantservices.com/rss/",
    "Chemical Engineering": "https://www.chemengonline.com/feed/",

    # Workforce and safety
    "NCCER Blog": "https://www.nccer.org/news/feed/",
    "OSHA QuickTakes": "https://www.osha.gov/quicktakes/feed",

    # Project management and bidding
    "Dodge Data Blog": "https://www.construction.com/blog/feed/",
    "ENR Articles": "https://www.enr.com/articles/feed",

    # Estimating software vendors (their blogs catch industry trends)
    "SmartBid Blog": "https://www.smartbidnet.com/blog/rss.xml",
}

KEYWORDS = [
    "estimat", "takeoff", "take-off", "MTO", "material takeoff",
    "quantity survey", "cost estimat", "bid manage",
    "P&ID", "piping", "isometric", "pipe spool",
    "mechanical contractor", "process piping", "ASME B31",
    "bluebeam", "planswift", "HCSS", "accubid", "fastpipe",
    "sage estimating", "procore estimating", "quoteSoft",
    "on-screen takeoff", "McCormick", "ConstructConnect", "WenPipe",
    "bid", "bidding", "preconstruction", "pre-construction",
    "go/no-go", "bid-hit ratio", "win rate",
    "AI takeoff", "AI estimat", "automation",
    "artificial intelligence construct",
    "burnout", "shortage", "retire", "hiring estimator",
    "workforce develop", "skilled labor", "craft worker",
    "apprentice", "training program",
    "Excel spreadsheet", "manual takeoff", "accuracy",
    "labor hours", "man-hours", "manhours", "labor unit",
    "MCAA labor", "SMACNA",
    "cost overrun", "change order", "scope creep", "rework",
    "turnaround", "refinery", "petrochemical", "gulf coast",
    "industrial contractor", "EPC",
    "data center", "backlog", "workforce",
    "software", "digital", "construction technology",
    "BIM", "prefab", "modular",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUTPUT_DIR = Path("output")


def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL. Catches ALL exceptions so one bad source never kills the scan."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] Failed: {e}", file=sys.stderr)
        return None


def clean_xml(text: str) -> str:
    """Pre-process XML to handle common RSS issues."""
    xml_start = text.find("<?xml")
    if xml_start == -1:
        xml_start = text.find("<rss")
    if xml_start == -1:
        xml_start = text.find("<feed")
    if xml_start > 0:
        text = text[xml_start:]
    text = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    for old, new in [('&nbsp;',' '),('&mdash;','-'),('&ndash;','-'),
                     ('&lsquo;',"'"),('&rsquo;',"'"),('&ldquo;','"'),
                     ('&rdquo;','"'),('&hellip;','...')]:
        text = text.replace(old, new)
    return text


def strip_html(text: str) -> str:
    text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.DOTALL)
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def matches_keywords(text: str) -> list:
    text_lower = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in text_lower]


def parse_rss(xml_text: str, source_name: str) -> list:
    results = []
    xml_text = clean_xml(xml_text)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  [WARN] XML parse error: {e}", file=sys.stderr)
        return []

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "dc": "http://purl.org/dc/elements/1.1/",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    items = root.findall(".//item")
    if not items:
        items = root.findall(".//atom:entry", ns)

    for item in items:
        title_el = item.find("title") or item.find("atom:title", ns)
        link_el = item.find("link") or item.find("atom:link", ns)
        content_el = item.find("content:encoded", ns)
        desc_el = item.find("description") or item.find("atom:summary", ns)
        pubdate_el = item.find("pubDate") or item.find("atom:updated", ns) or item.find("atom:published", ns)
        creator_el = item.find("dc:creator", ns)
        author_el = item.find("author")
        category_el = item.find("category")

        title = strip_html(title_el.text) if title_el is not None and title_el.text else ""
        link = ""
        if link_el is not None:
            link = link_el.get("href", "") or (link_el.text or "")
        if content_el is not None and content_el.text:
            description = strip_html(content_el.text)
        elif desc_el is not None and desc_el.text:
            description = strip_html(desc_el.text)
        else:
            description = ""
        pubdate = pubdate_el.text.strip() if pubdate_el is not None and pubdate_el.text else ""
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
                "date": pubdate,
                "author": author.strip(),
                "preview": description[:400],
                "matched_keywords": ", ".join(sorted(set(matched))),
                "category": category,
            })

    return results


def run_scan():
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outfile = OUTPUT_DIR / f"estimator_scan_{timestamp}.csv"

    all_results = []
    working = 0
    failed = 0
    failed_names = []

    print(f"=== Estimator Scan v4 ({timestamp}) ===\n")

    for name, feed_url in RSS_FEEDS.items():
        print(f"Scanning {name}...")
        xml_text = fetch_url(feed_url)
        if xml_text:
            items = parse_rss(xml_text, name)
            all_results.extend(items)
            print(f"  OK: {len(items)} matching items")
            working += 1
        else:
            failed += 1
            failed_names.append(name)
        time.sleep(1)

    # Deduplicate
    seen = set()
    deduped = []
    for r in all_results:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)
    all_results = deduped

    # Write CSV
    fields = ["source","title","url","date","author","preview","matched_keywords","category"]
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        if all_results:
            w.writerows(all_results)

    print(f"\nWrote {len(all_results)} items to {outfile}")
    print(f"\n--- Summary ---")
    print(f"Working: {working}/{len(RSS_FEEDS)}")
    print(f"Failed: {failed}/{len(RSS_FEEDS)}")
    if failed_names:
        print(f"Failed sources: {', '.join(failed_names)}")
    print(f"Total items: {len(all_results)}")
    if all_results:
        by_source = {}
        for r in all_results:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        print("\nBy source:")
        for s, c in sorted(by_source.items(), key=lambda x: -x[1]):
            print(f"  {s}: {c}")
        kw_counts = {}
        for r in all_results:
            for kw in r["matched_keywords"].split(", "):
                kw = kw.strip()
                if kw:
                    kw_counts[kw] = kw_counts.get(kw, 0) + 1
        print("\nTop keywords:")
        for kw, c in sorted(kw_counts.items(), key=lambda x: -x[1])[:15]:
            print(f"  {kw}: {c}")

    return outfile


if __name__ == "__main__":
    run_scan()
