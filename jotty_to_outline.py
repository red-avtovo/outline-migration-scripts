#!/usr/bin/env python3

import argparse
import re
import sys
import time
import requests
from tqdm import tqdm

API_SUFFIX = "/api"


class JottyClient:
    def __init__(self, host: str, api_key: str):
        self.base = host.rstrip("/") + API_SUFFIX
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key})

    def list_notes(self) -> list[dict]:
        r = self.session.get(f"{self.base}/notes")
        r.raise_for_status()
        return r.json()["notes"]


class OutlineClient:
    def __init__(self, host: str, api_key: str):
        self.base = host.rstrip("/") + API_SUFFIX
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _post(self, method: str, payload: dict) -> dict:
        url = f"{self.base}/{method}"
        for _ in range(5):
            r = self.session.post(url, json=payload)
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After", "60")
                try:
                    wait = int(float(retry_after))
                except ValueError:
                    wait = 60
                print(f"Rate limit hit. Waiting {wait}s...")
                time.sleep(wait)
                continue
            if not r.ok:
                raise RuntimeError(f"{method} → {r.status_code}: {r.text}")
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"{method} error: {data}")
            return data["data"]
        raise RuntimeError(f"{method} failed after retries")

    def get_or_create_collection(self, name: str) -> str:
        existing = self._post("collections.list", {"query": name})
        for col in existing:
            if col["name"].lower() == name.lower():
                return col["id"]
        return self._post("collections.create", {
            "name": name,
            "icon": "📝",
        })["id"]

    def create_document(self, title: str, text: str, collection_id: str, parent_id: str = None) -> dict:
        payload = {
            "title": title,
            "text": text,
            "collectionId": collection_id,
            "publish": True,
        }
        if parent_id:
            payload["parentDocumentId"] = parent_id
        return self._post("documents.create", payload)


def pretty_title(segment: str) -> str:
    return re.sub(r"[-_]+", " ", segment).title()


def migrate(jotty_host: str, jotty_key: str, outline_host: str, outline_key: str, collection_name: str):
    jotty = JottyClient(jotty_host, jotty_key)
    outline = OutlineClient(outline_host, outline_key)

    print("Fetching notes from Jotty...")
    notes = jotty.list_notes()
    print(f"Found {len(notes)} notes")

    collection_id = outline.get_or_create_collection(collection_name)
    print(f"Outline collection: {collection_id}")

    # Build the full set of category path segments we need as parent docs
    all_segments: set[tuple[str, ...]] = set()
    for note in notes:
        category = note.get("category") or "Uncategorized"
        parts = tuple(p.strip() for p in category.split("/") if p.strip())
        for depth in range(1, len(parts) + 1):
            all_segments.add(parts[:depth])

    # Sort by depth so parents are created before children
    sorted_segments = sorted(all_segments, key=lambda p: len(p))

    # Create placeholder docs for each category path segment
    segment_doc_map: dict[tuple[str, ...], str] = {}  # path tuple -> doc id

    for seg_path in tqdm(sorted_segments, desc="Create category docs"):
        parent_id = segment_doc_map.get(seg_path[:-1]) if len(seg_path) > 1 else None
        title = pretty_title(seg_path[-1])
        doc = outline.create_document(title, f"# {title}", collection_id, parent_id)
        segment_doc_map[seg_path] = doc["id"]

    # Upload each note under its category doc
    for note in tqdm(notes, desc="Upload notes"):
        category = note.get("category") or "Uncategorized"
        parts = tuple(p.strip() for p in category.split("/") if p.strip())
        parent_id = segment_doc_map.get(parts)
        content = note.get("content") or ""
        outline.create_document(note["title"], content, collection_id, parent_id)

    print("Migration complete.")


def main():
    p = argparse.ArgumentParser(description="Migrate Jotty notes to Outline")
    p.add_argument("--jotty-host", required=True, help="Jotty base URL, e.g. https://jotty.example.com")
    p.add_argument("--jotty-key", required=True, help="Jotty API key (ck_...)")
    p.add_argument("--outline-key", required=True, help="Outline API key")
    p.add_argument("--outline-host", default="https://app.getoutline.com")
    p.add_argument("--collection", default="Jotty Notes", help="Outline collection name")
    args = p.parse_args()

    migrate(
        jotty_host=args.jotty_host,
        jotty_key=args.jotty_key,
        outline_host=args.outline_host,
        outline_key=args.outline_key,
        collection_name=args.collection,
    )


if __name__ == "__main__":
    main()
