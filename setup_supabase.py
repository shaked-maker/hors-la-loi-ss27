"""
One-time Supabase migration script.
- Creates storage buckets: cad-images, results
- Uploads all 63 CAD images to cad-images bucket
- Seeds the garments table from prompts_cache.json

Run ONCE after executing schema.sql in Supabase SQL Editor:
  python3 setup_supabase.py
"""

import json
import os
from pathlib import Path
from supabase import create_client, Client

import os
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "client assets"
CACHE_FILE = BASE_DIR / "prompts_cache.json"


def get_public_url(supabase: Client, bucket: str, path: str) -> str:
    res = supabase.storage.from_(bucket).get_public_url(path)
    return res


def create_buckets(supabase: Client):
    for bucket in ("cad-images", "results"):
        try:
            supabase.storage.create_bucket(bucket, options={"public": True})
            print(f"  Bucket '{bucket}' created.")
        except Exception as e:
            if "already exists" in str(e).lower() or "Duplicate" in str(e):
                print(f"  Bucket '{bucket}' already exists — skipping.")
            else:
                raise


def upload_images(supabase: Client) -> dict:
    """Upload all CAD images and return mapping: filename -> public URL"""
    url_map = {}
    total = 0
    for collection in ("femme", "homme"):
        folder = ASSETS_DIR / collection
        if not folder.exists():
            print(f"  WARNING: folder not found: {folder}")
            continue
        images = [
            f for f in sorted(folder.iterdir())
            if f.suffix.lower() in (".jpg", ".jpeg", ".png")
            and f.name.lower() != "colors.jpg"
        ]
        print(f"\n  Uploading {len(images)} images from {collection}/...")
        for img_path in images:
            storage_path = f"{collection}/{img_path.name}"
            with open(img_path, "rb") as f:
                data = f.read()
            try:
                supabase.storage.from_("cad-images").upload(
                    path=storage_path,
                    file=data,
                    file_options={"content-type": "image/jpeg", "upsert": "true"},
                )
            except Exception as e:
                if "already exists" in str(e).lower():
                    pass  # already uploaded
                else:
                    print(f"    WARNING upload failed for {img_path.name}: {e}")
            public_url = get_public_url(supabase, "cad-images", storage_path)
            cache_key = f"{collection}/{img_path.name}"
            url_map[cache_key] = public_url
            total += 1
            print(f"    ✓ {storage_path}")
    print(f"\n  Total images uploaded: {total}")
    return url_map


def seed_table(supabase: Client, url_map: dict):
    """Insert/upsert all garments from prompts_cache.json"""
    if not CACHE_FILE.exists():
        print("  ERROR: prompts_cache.json not found. Skipping table seed.")
        return

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    rows = []
    for cache_key, data in cache.items():
        parts = cache_key.split("/", 1)
        if len(parts) != 2:
            continue
        collection, filename = parts
        rows.append({
            "collection": collection,
            "filename": filename,
            "model_code": data.get("model_code", ""),
            "prompt": data.get("prompt", ""),
            "cad_image_url": url_map.get(cache_key, ""),
            "result_url": data.get("result_file", ""),
        })

    print(f"\n  Upserting {len(rows)} rows into garments table...")
    # Upsert in batches of 20
    batch_size = 20
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        supabase.table("garments").upsert(batch, on_conflict="collection,filename").execute()
        print(f"    Batch {i // batch_size + 1}: {len(batch)} rows")

    print(f"  Done — {len(rows)} garments in Supabase.")


def main():
    print("=== Hors La Loi — Supabase Setup ===\n")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("1. Creating storage buckets...")
    create_buckets(supabase)
    print("\n2. Uploading CAD images to cad-images bucket...")
    url_map = upload_images(supabase)
    print("\n3. Seeding garments table...")
    seed_table(supabase, url_map)
    print("\n=== Setup complete! ===")
    print(f"   Supabase URL: {SUPABASE_URL}")
    print("   Open Supabase dashboard to verify data.")


if __name__ == "__main__":
    main()
