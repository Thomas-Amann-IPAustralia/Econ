"""Assemble the GitHub Pages site in _site/: the static front end, its config, the catalogue and the PDFs.

  python deploy/pages/build_site.py [--out _site]

- config.js gets the API URL from RENDER_API_URL (a repository variable in the Pages workflow).
- data/catalogue.json is library/index/docs.json, so the library view loads without waking the API.
- pdfs/<doc_id>.pdf are copied from R2 when R2_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are
  set; the page viewer needs them to draw a passage on its page. They are published with the site, not
  committed to git.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    api = os.environ.get("RENDER_API_URL", "").strip().rstrip("/")
    (out / "config.js").write_text(
        "window.ECON_CONFIG = " + json.dumps({"api": api, "pdfBase": "pdfs/"}) + ";\n", encoding="utf-8"
    )
    index = Path(os.environ.get("ECON_INDEX_DIR") or ROOT / "library/index")
    docs = json.loads((index / "docs.json").read_text())
    meta = json.loads((index / "index.json").read_text())
    (out / "data").mkdir(exist_ok=True)
    (out / "data/catalogue.json").write_text(json.dumps({"documents": docs, "index": meta}), encoding="utf-8")
    (out / ".nojekyll").write_text("")

    keys = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    if not all(os.environ.get(k) for k in keys):
        print("R2 secrets not set: the site is built without PDFs (the page viewer will link out instead)")
        return
    import boto3

    src = yaml.safe_load((ROOT / "config/sources.yaml").read_text())
    s3 = boto3.client(
        "s3",
        endpoint_url=src["endpoint"].format(account_id=os.environ["R2_ACCOUNT_ID"]),
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    (out / "pdfs").mkdir(exist_ok=True)
    for d in src["documents"]:
        if d["doc_id"] not in docs:
            continue  # registered but not yet served (the WIPO documents, D-033): not published
        dest = out / "pdfs" / f"{d['doc_id']}.pdf"
        s3.download_file(src["bucket"], d["key"], str(dest))
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        expected = docs[d["doc_id"]]["source_sha256"]
        if digest != expected:
            sys.exit(
                f"{d['doc_id']}: the PDF in R2 changed since the index was built ({digest[:12]} != {expected[:12]})"
            )
    print(f"copied {len(list((out / 'pdfs').glob('*.pdf')))} PDFs from R2")


if __name__ == "__main__":
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "_site"
    main(out)
