import os
import base64
from pathlib import Path
from flask import Flask, jsonify, render_template, send_file, request, redirect
from dotenv import load_dotenv
from supabase import create_client, Client
import anthropic

load_dotenv()

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "client assets"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def image_to_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


EXTRACTION_SYSTEM = """You are a fashion technical analyst. You analyze CAD spec sheets for garments.
You will receive two images:
1. A garment spec sheet (artboard) showing front and back views, model code, fabric info, and color
2. A color card showing all available colors with their names and codes

Extract all relevant information and output ONLY the formatted flatlay prompt — no extra text, no explanation."""

EXTRACTION_USER = """Analyze this garment spec sheet and the color card reference, then produce the flatlay prompt.

Use EXACTLY this format (replace placeholders with real values from the spec sheet):

Create a clean flatlay from the provided CAD.
{{GARMENT_TYPE}}, exact proportions
Front and back views.
Color:
{{AREA_1}} — {{COLOR_NAME_1}} ({{HEX_1}})
{{FRONT_DETAIL}}
{{BACK_DETAIL}}
Fabric:
{{AREA_1}} — {{FABRIC_NAME_1}}, {{TEXTURE_1}}
Clean panel lines and stitching.
Pure white background (#FFFFFF), centered, perfectly flat, soft shadow.

Rules:
- GARMENT_TYPE: full description e.g. "Cropped S/S T-shirt, boxy fit, dropped shoulders"
- COLOR areas: use the actual area name (e.g. "Body", "Collar", "Panels")
- COLOR_NAME: exact name from the color card (e.g. "Noir / BK001 Black")
- HEX: approximate hex based on the color card swatch
- FRONT_DETAIL: describe front graphic/print if any — omit line if none
- BACK_DETAIL: describe back graphic/print if any — omit line if none
- FABRIC areas: from the spec sheet fabric field
- Include all fabric components listed

Also include on the VERY FIRST LINE before the prompt (this line will be stripped):
MODEL_CODE: <the code from the spec sheet top-left box, e.g. HLK4401.QAFF>"""


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/garments")
def api_garments():
    res = supabase.table("garments").select("*").order("collection").order("filename").execute()
    garments = []
    for row in res.data:
        garments.append({
            "collection": row["collection"],
            "filename": row["filename"],
            "cache_key": f"{row['collection']}/{row['filename']}",
            "model_code": row.get("model_code") or "",
            "prompt": row.get("prompt") or "",
            "result_file": row.get("result_url") or "",
            "cad_image_url": row.get("cad_image_url") or "",
        })
    return jsonify(garments)


@app.route("/images/<collection>/<path:filename>")
def serve_image(collection, filename):
    """Serve CAD images locally (files are on disk)."""
    path = ASSETS_DIR / collection / filename
    if not path.exists():
        return "Not found", 404
    return send_file(path)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json()
    collection = data.get("collection")
    filename = data.get("filename")
    force = data.get("force", False)

    if not collection or not filename:
        return jsonify({"error": "Missing collection or filename"}), 400

    # Check if already generated
    if not force:
        res = supabase.table("garments").select("model_code,prompt").eq("collection", collection).eq("filename", filename).single().execute()
        if res.data and res.data.get("prompt"):
            return jsonify({"model_code": res.data["model_code"], "prompt": res.data["prompt"]})

    garment_path = ASSETS_DIR / collection / filename
    colors_path = ASSETS_DIR / collection / "colors.jpg"

    if not garment_path.exists():
        return jsonify({"error": "Image not found"}), 404

    garment_b64 = image_to_base64(garment_path)
    images_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": garment_b64}},
    ]
    if colors_path.exists():
        images_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_to_base64(colors_path)},
        })
    images_content.append({"type": "text", "text": EXTRACTION_USER})

    try:
        response = anthropic_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": images_content}],
        )
        raw = response.content[0].text.strip()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    model_code = ""
    lines = raw.split("\n")
    if lines and lines[0].startswith("MODEL_CODE:"):
        model_code = lines[0].replace("MODEL_CODE:", "").strip()
        prompt = "\n".join(lines[1:]).strip()
    else:
        prompt = raw

    # Save to Supabase
    supabase.table("garments").update({
        "model_code": model_code,
        "prompt": prompt,
    }).eq("collection", collection).eq("filename", filename).execute()

    return jsonify({"model_code": model_code, "prompt": prompt})


@app.route("/api/upload/<collection>/<path:filename>", methods=["POST"])
def api_upload(collection, filename):
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    f = request.files["file"]

    # Get model_code from Supabase
    res = supabase.table("garments").select("model_code").eq("collection", collection).eq("filename", filename).single().execute()
    model_code = (res.data or {}).get("model_code", "") if res.data else ""

    ext = Path(f.filename).suffix or ".jpg"
    save_name = f"{model_code}{ext}" if model_code else f"{Path(filename).stem}_result{ext}"
    storage_path = save_name

    file_bytes = f.read()
    try:
        supabase.storage.from_("results").upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": "image/jpeg", "upsert": "true"},
        )
    except Exception as e:
        if "already exists" not in str(e).lower():
            return jsonify({"error": f"Upload failed: {e}"}), 500

    public_url = supabase.storage.from_("results").get_public_url(storage_path)

    # Update Supabase record
    supabase.table("garments").update({"result_url": public_url}).eq("collection", collection).eq("filename", filename).execute()

    return jsonify({"result_file": save_name, "url": public_url})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
