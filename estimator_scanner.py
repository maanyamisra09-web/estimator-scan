#!/usr/bin/env python3
"""
Estimator & Construction Forum/Review Scanner
Scans estimation-relevant forums (RSS), review sites, and industry news
for content ideas and pain points. No API keys needed.

Schedule via GitHub Actions cron (see .github/workflows/scan.yml).
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

# RSS Feeds (forums, news, industry)
RSS_FEEDS = {
    "Eng-Tips: Piping": "https://www.eng-tips.com/rss/forum.cfm?fid=50",
    "Eng-Tips: Mechanical": "https://www.eng-tips.com/rss/forum.cfm?fid=52",
    "Eng-Tips: Structural": "https://www.eng-tips.com/rss/forum.cfm?fid=151",
    "Construction Dive": "https://www.constructiondive.com/feeds/news/",
    "Construction Dive: Technology": "https://www.constructiondive.com/feeds/topic/construction-technology/",
    "ENR: Construction": "https://www.enr.com/feeds/topics/7-construction",
    "ENR: Technology": "https://www.enr.com/feeds/topics/93-technology",
    "For Construction Pros": "https://www.forconstructionpros.com/rss",
    "JLC Online": "https://www.jlconline.com/rss",
}

# Google search queries for review sites and forums without RSS
GOOGLE_QUERIES = [
    'site:g2.com "Bluebeam" estimating review 2025 OR 2026',
    'site:g2.com "PlanSwift" OR "HCSS" estimating review 2025 OR 2026',
    'site:capterra.com "piping estimating" OR "construction estimating" review 2025 OR 2026',
    'site:capterra.com "Bluebeam" OR "FastPIPE" review 2025 OR 2026',
    'site:contractortalk.com estimating OR takeoff OR bidding',
    'site:eng-tips.com "piping estimating" OR "material takeoff" OR "P&ID"',
    '"construction estimator" burnout OR shortage OR hiring OR retirement 2025 OR 2026',
    '"estimating software" frustration OR complaint OR switching OR replacement',
    '"AI takeoff" OR "AI estimating" construction piping mechanical',
    '"data center" piping contractor estimating backlog',
]

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
    "data center", "backlog",
]

USER_AGENT = "Mozilla/5.0 (compatible; EstimatorScanner/2.0)"
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

        combined = f"{title} {description}"
        matched = matches_keywords(combined)

        if matched:
            results.append({
                "source": source_name,
                "title": title.strip(),
                "url": link.strip(),
                "score": 0,
                "num_comments": 0,
                "created_utc": pubdate.strip(),
                "author": source_name,
                "selftext_preview": description[:300],
                "matched_keywords": ", ".join(sorted(set(matched))),
                "flair": "RSS",
            })

    return results


def google_search_scrape(query: str) -> list:
    """Search Google and extract result URLs and titles from the HTML.
    This is best-effort and may fail if Google blocks the request."""
    encoded = urllib.request.quote(query)
    url = f"https://www.google.com/search?q={encoded}&num=10"
    html = fetch_url(url)
    if not html:
        return []

    results = []
    # Extract search result links - pattern for Google's result HTML
    # This is fragile and may break, but works as a fallback
    link_pattern = re.compile(r'<a[^>]+href="/url\?q=(https?://[^&"]+)', re.IGNORECASE)
    title_pattern = re.compile(r'<h3[^>]*>(.*?)</h3>', re.IGNORECASE | re.DOTALL)

    links = link_pattern.findall(html)
    titles = [strip_html(t) for t in title_pattern.findall(html)]

    for i, link in enumerate(links[:10]):
        link = urllib.request.unquote(link)
        title = titles[i] if i < len(titles) else ""
        combined = f"{title} {link}"
        matched = matches_keywords(combined)

        if matched:
            results.append({
                "source": "Google Search",
                "title": title,
                "url": link,
                "score": 0,
                "num_comments": 0,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "author": "Google Search",
                "selftext_preview": f"Query: {query}",
                "matched_keywords": ", ".join(sorted(set(matched))),
                "flair": "Search",
            })

    return results


def run_scan():
    """Main scan loop."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outfile = OUTPUT_DIR / f"estimator_scan_{timestamp}.csv"

    all_results = []

    # Phase 1: RSS Feeds
    print("=== Phase 1: RSS Feeds ===\n")
    for name, feed_url in RSS_FEEDS.items():
        print(f"Scanning {name}...")
        xml_text = fetch_url(feed_url)
        if xml_text:
            items = parse_rss(xml_text, name)
            all_results.extend(items)
            print(f"  Found {len(items)} matching items")
        time.sleep(1)

    # Phase 2: Google searches for review sites and forums
    print("\n=== Phase 2: Review Sites & Forum Search ===\n")
    for query in GOOGLE_QUERIES:
        print(f"Searching: {query[:60]}...")
        items = google_search_scrape(query)
        all_results.extend(items)
        print(f"  Found {len(items)} results")
        time.sleep(3)  # be polite to Google

    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            deduped.append(r)
    all_results = deduped

    # Write CSV
    fieldnames = [
        "source", "title", "url", "score", "num_comments",
        "created_utc", "author", "selftext_preview", "matched_keywords", "flair"
    ]
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if all_results:
            writer.writerows(all_results)

    print(f"\nWrote {len(all_results)} items to {outfile}")

    # Summary stats
    print(f"\n--- Scan Summary ({timestamp}) ---")
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
