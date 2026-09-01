#!/usr/bin/env python3
"""
Estimator & Construction Forum/Review Scanner v5
Fixed XML element truthiness bug. Crash-proof. No API keys.
"""

import csv
import re
import sys
import time
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from html import unescape

RSS_FEEDS = {
    "Construction Dive": "https://www.constructiondive.com/feeds/news/",
    "For Construction Pros": "https://www.forconstructionpros.com/rss",
    "Construction Business Owner": "https://www.constructionbusinessowner.com/rss.xml",
    "AGC News": "https://www.agc.org/rss.xml",
    "ConstructConnect Blog": "https://www.constructconnect.com/blog/rss.xml",
    "Procore Jobsite Blog": "https://www.procore.com/jobsite/feed/",
    "MCAA News": "https://www.mcaa.org/feed/",
    "PHCC Connect": "https://www.phccweb.org/feed/",
    "Chemical Engineering": "https://www.chemengonline.com/feed/",
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


def fetch_url(url, timeout=15):
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


def clean_xml(text):
    for start_tag in ["<?xml", "<rss", "<feed"]:
        idx = text.find(start_tag)
        if idx > 0:
            text = text[idx:]
            break
    text = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    for old, new in [('&nbsp;',' '),('&mdash;','-'),('&ndash;','-'),
                     ('&lsquo;',"'"),('&rsquo;',"'"),('&ldquo;','"'),
                     ('&rdquo;','"'),('&hellip;','...')]:
        text = text.replace(old, new)
    return text


def strip_html(text):
    text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_el(item, *paths, ns=None):
    """Find first matching element. Replaces broken 'or' pattern."""
    if ns is None:
        ns = {}
    for path in paths:
        el = item.find(path, ns)
        if el is not None:
            return el
    return None


def get_text(el):
    """Safely get text from an element."""
    if el is None:
        return ""
    return (el.text or "").strip()


def get_link(el):
    """Get URL from a link element (handles both RSS and Atom)."""
    if el is None:
        return ""
    href = el.get("href", "")
    if href:
        return href.strip()
    return (el.text or "").strip()


def matches_keywords(text):
    text_lower = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in text_lower]


def parse_rss(xml_text, source_name):
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
        title_el = find_el(item, "title", "atom:title", ns=ns)
        link_el = find_el(item, "link", "atom:link", ns=ns)
        content_el = find_el(item, "content:encoded", ns=ns)
        desc_el = find_el(item, "description", "atom:summary", "atom:content", ns=ns)
        pubdate_el = find_el(item, "pubDate", "atom:updated", "atom:published", ns=ns)
        creator_el = find_el(item, "dc:creator", ns=ns)
        author_el = find_el(item, "author", ns=ns)
        category_el = find_el(item, "category", ns=ns)

        title = strip_html(get_text(title_el))
        link = get_link(link_el)

        if content_el is not None and content_el.text:
            description = strip_html(content_el.text)
        else:
            description = strip_html(get_text(desc_el))

        pubdate = get_text(pubdate_el)
        author = get_text(creator_el) or get_text(author_el) or source_name
        category = strip_html(get_text(category_el))

        combined = f"{title} {description}"
        matched = matches_keywords(combined)
        if matched:
            results.append({
                "source": source_name,
                "title": title,
                "url": link,
                "date": pubdate,
                "author": author,
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

    print(f"=== Estimator Scan v5 ({timestamp}) ===\n")

    for name, feed_url in RSS_FEEDS.items():
        print(f"Scanning {name}...")
        xml_text = fetch_url(feed_url)
        if xml_text:
            items = parse_rss(xml_text, name)
            all_results.extend(items)
            print(f"  OK: {len(items)} matching / URLs present: {sum(1 for i in items if i['url'])}")
            working += 1
        else:
            failed += 1
            failed_names.append(name)
        time.sleep(1)

    # Deduplicate by URL, but keep items with empty URLs too
    seen = set()
    deduped = []
    for r in all_results:
        url = r["url"]
        if not url:
            deduped.append(r)
        elif url not in seen:
            seen.add(url)
            deduped.append(r)
    all_results = deduped

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
        print(f"Failed: {', '.join(failed_names)}")
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
