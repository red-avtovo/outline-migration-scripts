#!/usr/bin/env python3

import argparse
import mimetypes
import os
import re
import sys
import time
from pathlib import Path
import requests
from tqdm import tqdm

API_SUFFIX = "/api"

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

    def get_or_create_collection(self, name: str, description: str = "") -> str:
        existing = self._post("collections.list", {"query": name})
        for col in existing:
            if col["name"].lower() == name.lower():
                return col["id"]
        icon = guess_icon(name, default="📚")
        return self._post("collections.create", {
            "name": name,
            "description": description,
            "icon": icon
        })["id"]

    def update_collection_description(self, collection_id: str, description: str):
        self._post("collections.update", {
            "id": collection_id,
            "description": description
        })

    def create_document(self, title: str, text: str, collection_id: str, parent_id: str | None = None) -> dict:
        payload = {
            "title": title,
            "text": text,
            "collectionId": collection_id,
            "icon": guess_icon(title),
            "publish": True
        }
        if parent_id:
            payload["parentDocumentId"] = parent_id
        return self._post("documents.create", payload)

    def upload_attachment(self, path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        meta = {
            "name": path.name,
            "contentType": mime,
            "size": path.stat().st_size,
        }
        resp = self._post("attachments.create", meta)
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, mime)}
            requests.post(resp["uploadUrl"], data=resp["form"], files=files).raise_for_status()
        return resp["attachment"]["url"]

def guess_icon(title: str, default: str = "📄") -> str:
    t = title.lower()
    if "home" in t: return "🏠"
    if "intro" in t or "start" in t: return "🏁"
    if "install" in t or "setup" in t: return "🛠️"
    if "faq" in t or "help" in t: return "❓"
    if "guide" in t or "tutorial" in t: return "📘"
    if "advanced" in t: return "🔬"
    if "api" in t: return "🔌"
    if "diagram" in t or "arch" in t: return "🗂️"
    return default

IMG_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
MD_LINK_RE = re.compile(r"\[([^\]]+)]\(([^)]+)\)")

def rewrite_markdown(md: str, root: Path, client: OutlineClient) -> str:
    def sub_img(m):
        path = (root / m.group(1).split(" ")[0]).resolve()
        return m.group(0).replace(m.group(1), client.upload_attachment(path)) if path.exists() else m.group(0)
    return IMG_RE.sub(sub_img, md)

def fix_internal_links(md: str, url_map: dict[str, tuple[str, str]]) -> str:
    def replace_link(m):
        label, link = m.group(1).strip(), m.group(2).split("|")[0].strip()
        base = os.path.splitext(os.path.basename(link))[0].lower()
        if base in url_map:
            title, urlid = url_map[base]
            slug = re.sub(r"[^\w\s-]", "", title).strip().lower()
            slug = re.sub(r"[\s_-]+", "-", slug)
            return f"[{label}](/doc/{slug}-{urlid})"
        return m.group(0)
    return MD_LINK_RE.sub(replace_link, md)

def pretty_title(path: Path) -> str:
    return re.sub(r"[-_]+", " ", path.stem).title()


def is_substantive(md: str) -> bool:
    """Return True if the note has more than 2 non-empty lines."""
    non_empty = [l for l in md.splitlines() if l.strip()]
    return len(non_empty) > 2


def export_repo(repo_path: Path, client: OutlineClient, collection_name: str):
    files = sorted(p for p in repo_path.rglob("*.md") if p.is_file())
    home_path = next((f for f in files if f.stem.lower() == "home"), None)
    home_raw = home_path.read_text(encoding="utf-8") if home_path else ""

    # Prepare all documents
    docs = []
    for f in tqdm(files, desc="Prepare"):
        raw = f.read_text(encoding="utf-8")
        md = rewrite_markdown(raw, f.parent, client)
        docs.append((f, pretty_title(f), md))

    temp_map = {f.stem.lower(): (title, "temp") for f, title, _ in docs}
    collection_id = client.get_or_create_collection(
        collection_name,
        fix_internal_links(home_raw, temp_map).strip()
    )

    # Build document tree and upload hierarchically
    url_map = {}
    parent_map = {}  # Maps directory path to parent document ID
    
    # Collect all directories that contain markdown files
    all_dirs = set()
    for f in files:
        current = f.parent
        while current != repo_path and current not in all_dirs:
            all_dirs.add(current)
            current = current.parent
    
    # Sort directories by depth (shallowest first)
    sorted_dirs = sorted(all_dirs, key=lambda p: len(p.relative_to(repo_path).parts))
    
    # Create placeholder documents for directories
    for dir_path in tqdm(sorted_dirs, desc="Create folders"):
        parent_id = None
        if dir_path.parent != repo_path:
            parent_id = parent_map.get(dir_path.parent)
        
        # Create a placeholder document for this directory
        dir_name = pretty_title(Path(dir_path.name))
        doc = client.create_document(dir_name, f"# {dir_name}\n\nDocuments in this section:", collection_id, parent_id)
        parent_map[dir_path] = doc["id"]
    
    # Upload all markdown files
    for f, title, content in tqdm(docs, desc="Upload"):
        parent_id = parent_map.get(f.parent)
        if not is_substantive(content):
            continue
        fixed_md = fix_internal_links(content, url_map)
        doc = client.create_document(title, fixed_md, collection_id, parent_id)
        url_map[f.stem.lower()] = (title, doc["urlId"])

    if home_raw.strip():
        fixed_home = fix_internal_links(home_raw, url_map).strip()
        client.update_collection_description(collection_id, fixed_home)

def main():
    p = argparse.ArgumentParser(description="Migrate an Obsidian vault to Outline")
    p.add_argument("repo", type=Path, metavar="vault", help="Path to the Obsidian vault directory")
    p.add_argument("--api-key", required=True, help="Outline API key")
    p.add_argument("--collection", help="Outline collection name (defaults to vault directory name)")
    p.add_argument("--host", default="https://app.getoutline.com", help="Outline instance URL")
    args = p.parse_args()

    if not args.repo.is_dir():
        sys.exit("Not a directory: " + str(args.repo))

    client = OutlineClient(args.host, args.api_key)
    export_repo(args.repo, client, args.collection or args.repo.stem)

if __name__ == "__main__":
    main()
