#!/usr/bin/env python3
"""
plex_check.py
Simple CLI to search Plex for a movie or show with exact and fuzzy matching.
Requires: plexapi, rapidfuzz, python-dotenv
"""

from dotenv import load_dotenv
import os
import sys
import time
import json
import argparse
from pathlib import Path
from plexapi.server import PlexServer
from rapidfuzz import fuzz

# Load .env
load_dotenv()

# Configuration
PLEX_BASE = os.environ.get("PLEX_BASE", "http://10.0.0.208:32400")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN")
if not PLEX_TOKEN:
    sys.exit("PLEX_TOKEN not set. Put it in .env or export it in your environment.")

CACHE_FILE = Path.home() / ".plex_cache.json"
CACHE_TTL = 60 * 60 * 6  # 6 hours

# Connect to Plex
try:
    plex = PlexServer(PLEX_BASE, PLEX_TOKEN)
except Exception as e:
    sys.exit(f"Failed to connect to Plex at {PLEX_BASE}: {e}")

def load_cache():
    if not CACHE_FILE.exists():
        return {"updated": 0, "libraries": {}}
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {"updated": 0, "libraries": {}}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache))

def refresh_cache(force=False):
    cache = load_cache()
    now = time.time()
    if not force and (now - cache.get("updated", 0) < CACHE_TTL):
        return cache
    libraries = {}
    for section in plex.library.sections():
        try:
            items = []
            for item in section.all():
                items.append({
                    "title": item.title,
                    "year": getattr(item, "year", None),
                    "type": item.type,
                    "ratingKey": item.ratingKey
                })
            libraries[str(section.key)] = {
                "title": section.title,
                "type": section.type,
                "items": items
            }
        except Exception:
            continue
    cache = {"updated": now, "libraries": libraries}
    save_cache(cache)
    return cache

def search_exact(title, section_id=None):
    title_norm = title.strip().lower()
    try:
        if section_id is not None:
            section = plex.library.sectionByID(section_id)
            results = section.search(title)
        else:
            results = plex.search(title, mediatype="movie")
    except Exception:
        # fallback to server-wide search if section lookup fails
        results = plex.search(title)
    matches = []
    for r in results:
        if getattr(r, "title", "").strip().lower() == title_norm:
            matches.append({
                "title": r.title,
                "year": getattr(r, "year", None),
                "type": r.type,
                "ratingKey": r.ratingKey,
                "library": r.librarySectionTitle
            })
    return matches

def search_fuzzy(title, threshold=80, section_id=None, cache=None):
    title_norm = title.strip().lower()
    if cache is None:
        cache = refresh_cache()
    items = []
    if section_id is not None:
        lib = cache["libraries"].get(str(section_id))
        if lib:
            items = lib["items"]
    else:
        for lib in cache["libraries"].values():
            items.extend(lib["items"])
    found = []
    for it in items:
        score = fuzz.token_sort_ratio(title_norm, it["title"].strip().lower())
        if score >= threshold:
            found.append({
                "title": it["title"],
                "year": it.get("year"),
                "score": score,
                "type": it.get("type"),
                "ratingKey": it.get("ratingKey")
            })
    return sorted(found, key=lambda x: x["score"], reverse=True)

def main():
    parser = argparse.ArgumentParser(description="Check Plex for a movie or show")
    parser.add_argument("--section", type=int, help="Library section ID to limit search", default=None)
    parser.add_argument("--fuzzy", action="store_true", help="Use fuzzy matching")
    parser.add_argument("--threshold", type=int, default=85, help="Fuzzy match threshold 0-100")
    parser.add_argument("--refresh", action="store_true", help="Force refresh cache")
    parser.add_argument("--title", type=str, help="Title to search (non-interactive)", default=None)
    args = parser.parse_args()

    if args.refresh:
        print("Refreshing cache...")
        refresh_cache(force=True)

    cache = refresh_cache()

    if args.title:
        title = args.title.strip()
    else:
        try:
            title = input("Enter movie or show name to search: ").strip()
        except KeyboardInterrupt:
            print("\nAborted.")
            return

    if not title:
        print("No title entered. Exiting.")
        return

    # Exact first
    exact = search_exact(title, section_id=args.section)
    if exact:
        print(f"\nExact match found ({len(exact)}):")
        for m in exact:
            print(f"- {m['title']} ({m['year']}) — {m['library']} — ratingKey {m['ratingKey']}")
        return

    if args.fuzzy:
        fuzzy_matches = search_fuzzy(title, threshold=args.threshold, section_id=args.section, cache=cache)
        if fuzzy_matches:
            print(f"\nFuzzy matches (threshold {args.threshold}):")
            for m in fuzzy_matches[:20]:
                print(f"- {m['title']} ({m.get('year')}) — score {m['score']} — ratingKey {m['ratingKey']}")
            return
        else:
            print("\nNo fuzzy matches found.")
            return

    print("\nNo exact match found. Showing server search results:")
    results = plex.search(title)
    if not results:
        print("No results from server search.")
        return

    for r in results[:20]:
        # prefer common title attributes, fall back to name/tag if needed
        title_val = getattr(r, "title", None) or getattr(r, "name", None) or getattr(r, "tag", None) or "<unknown>"
        rtype = getattr(r, "type", type(r).__name__)
        year = getattr(r, "year", "n/a")
        library = getattr(r, "librarySectionTitle", "n/a")
        ratingKey = getattr(r, "ratingKey", "n/a")
        print(f"- {title_val} ({year}) — {rtype} — {library} — ratingKey {ratingKey}")
        
def run_search(title, args, cache):
    # Exact first
    exact = search_exact(title, section_id=args.section)
    if exact:
        print(f"\nExact match found ({len(exact)}):")
        for m in exact:
            print(f"- {m['title']} ({m['year']}) — {m['library']} — ratingKey {m['ratingKey']}")
        return

    if args.fuzzy:
        fuzzy_matches = search_fuzzy(title, threshold=args.threshold, section_id=args.section, cache=cache)
        if fuzzy_matches:
            print(f"\nFuzzy matches (threshold {args.threshold}):")
            for m in fuzzy_matches[:20]:
                print(f"- {m['title']} ({m.get('year')}) — score {m['score']} — ratingKey {m['ratingKey']}")
            return
        else:
            print("\nNo fuzzy matches found.")
            return

    # If no exact and not fuzzy, show server search results (safe printing)
    print("\nNo exact match found. Showing server search results:")
    results = plex.search(title)
    if not results:
        print("No results from server search.")
        return
    for r in results[:20]:
        title_val = getattr(r, "title", None) or getattr(r, "name", None) or getattr(r, "tag", None) or "<unknown>"
        rtype = getattr(r, "type", type(r).__name__)
        year = getattr(r, "year", "n/a")
        library = getattr(r, "librarySectionTitle", "n/a")
        ratingKey = getattr(r, "ratingKey", "n/a")
        print(f"- {title_val} ({year}) — {rtype} — {library} — ratingKey {ratingKey}")

def main():
    parser = argparse.ArgumentParser(description="Check Plex for a movie or show")
    parser.add_argument("--section", type=int, help="Library section ID to limit search", default=None)
    parser.add_argument("--fuzzy", action="store_true", help="Use fuzzy matching")
    parser.add_argument("--threshold", type=int, default=85, help="Fuzzy match threshold 0-100")
    parser.add_argument("--refresh", action="store_true", help="Force refresh cache")
    parser.add_argument("--title", type=str, help="Title to search (non-interactive)", default=None)
    args = parser.parse_args()

    if args.refresh:
        print("Refreshing cache...")
        refresh_cache(force=True)

    cache = refresh_cache()

    # Non-interactive mode: run once and exit
    if args.title:
        run_search(args.title.strip(), args, cache)
        return

    # Interactive loop
    print("Type a movie/show name to search. Type 'exit' or 'quit' to stop.")
    try:
        while True:
            q = input("> ").strip()
            if not q:
                continue
            if q.lower() in ("exit", "quit"):
                print("Goodbye.")
                return
            run_search(q, args, cache)
    except KeyboardInterrupt:
        print("\nAborted by user.")
        return

if __name__ == "__main__":
    main()