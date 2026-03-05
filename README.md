# Outline Migration Scripts

Two scripts for migrating notes into [Outline](https://www.getoutline.com/).

## Requirements

```bash
pip install requests tqdm
```

---

## obsidian_to_outline.py

Migrates an Obsidian vault to Outline. Each subdirectory becomes a parent document, preserving the folder hierarchy. Local images are uploaded as attachments. Internal `[[wiki-style]]` and markdown links are rewritten to point to the created Outline documents. Notes with 2 or fewer non-empty lines are skipped.

**Usage**

```bash
python obsidian_to_outline.py <vault> --api-key <key> [--host <url>] [--collection <name>]
```

| Argument | Required | Description |
|---|---|---|
| `vault` | yes | Path to the Obsidian vault directory |
| `--api-key` | yes | Outline API key |
| `--host` | no | Outline instance URL (default: `https://app.getoutline.com`) |
| `--collection` | no | Collection name in Outline (default: vault directory name) |

**Example**

```bash
python obsidian_to_outline.py ~/Documents/MyVault \
  --api-key ol_api_... \
  --host https://outline.example.com \
  --collection "My Notes"
```

**What it does**

1. Scans the vault for all `.md` files
2. Uploads local images as Outline attachments and rewrites their URLs
3. Creates an Outline collection (or reuses one with the same name)
4. Creates placeholder parent documents for each subdirectory
5. Uploads each note (skipping near-empty ones) under its corresponding parent
6. Rewrites internal links to use Outline's `/doc/` URL format
7. If a `Home.md` exists, its content is used as the collection description

---

## jotty_to_outline.py

Migrates notes from a [Jotty](https://github.com/fccview/jotty) instance to Outline. Jotty's slash-separated categories (e.g. `Work/Projects/Backend`) are mapped to a nested document hierarchy.

**Usage**

```bash
python jotty_to_outline.py --jotty-host <url> --jotty-key <key> --outline-key <key> [--outline-host <url>] [--collection <name>]
```

| Argument | Required | Description |
|---|---|---|
| `--jotty-host` | yes | Jotty base URL, e.g. `https://jotty.example.com` |
| `--jotty-key` | yes | Jotty API key (`ck_...`) |
| `--outline-key` | yes | Outline API key |
| `--outline-host` | no | Outline instance URL (default: `https://app.getoutline.com`) |
| `--collection` | no | Collection name in Outline (default: `Jotty Notes`) |

**Example**

```bash
python jotty_to_outline.py \
  --jotty-host https://jotty.example.com \
  --jotty-key ck_... \
  --outline-key ol_api_... \
  --outline-host https://outline.example.com \
  --collection "Jotty Notes"
```

**What it does**

1. Fetches all notes from the Jotty API
2. Derives the full category tree from all note categories
3. Creates an Outline collection (or reuses one with the same name)
4. Creates a placeholder parent document for each category segment, shallowest first
5. Uploads each note under its deepest matching category document

**Category mapping example**

```
Jotty category: Work/Projects/Backend
                    │
                    ▼
Outline collection: Jotty Notes
  └── Work
       └── Projects
            └── Backend
                 └── (your note)
```
