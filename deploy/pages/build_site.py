"""Assemble the GitHub Pages site in _site/: the static front end, its config, the catalogue and the PDFs.

  python deploy/pages/build_site.py [--out _site]

- config.js gets the API URL from RENDER_API_URL (a repository variable in the Pages workflow).
- data/catalogue.json is every built corpus's docs.json (library/index/, and each other corpus's
  <library>/index/ when it exists, D-033), so the library view loads without waking the API. Each document
  says whether its PDF is on the site (`pdf`).
- pdfs/<doc_id>.pdf are copied from R2 when R2_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are
  set, for the corpora marked `pdfs_on_site` in config/pipeline.yaml (publishing a corpus's PDFs is the
  owner's call); the page viewer needs them to draw a passage on its page. They are published with the
  site, not committed to git.
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
    corpora = yaml.safe_load((ROOT / "config/pipeline.yaml").read_text()).get("corpora") or {
        "ipa": {"sources": "sources.yaml", "library": "library", "pdfs_on_site": True}
    }
    first = next(iter(corpora))
    keys = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    with_pdfs = all(os.environ.get(k) for k in keys)
    docs, meta, publish = {}, None, []
    for name, c in corpora.items():
        index = (
            Path(os.environ.get("ECON_INDEX_DIR") or ROOT / "library/index")
            if name == first
            else ROOT / c["library"] / "index"
        )
        if not (index / "docs.json").exists():
            continue  # a corpus not yet built
        part = json.loads((index / "docs.json").read_text())
        on_site = bool(c.get("pdfs_on_site")) and with_pdfs
        for d in part.values():
            d.setdefault("corpus", name)
            d["pdf"] = on_site
        docs.update(part)
        meta = meta or json.loads((index / "index.json").read_text())
        if on_site:
            publish.append(yaml.safe_load((ROOT / "config" / c["sources"]).read_text()))
    (out / "data").mkdir(exist_ok=True)
    (out / "data/catalogue.json").write_text(json.dumps({"documents": docs, "index": meta}), encoding="utf-8")
    (out / ".nojekyll").write_text("")

    if not with_pdfs:
        print("R2 secrets not set: the site is built without PDFs (the page viewer will link out instead)")
        return
    import boto3

    copied = 0
    for src in publish:
        s3 = boto3.client(
            "s3",
            endpoint_url=src["endpoint"].format(account_id=os.environ["R2_ACCOUNT_ID"]),
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        (out / "pdfs").mkdir(exist_ok=True)
        for d in src["documents"]:
            dest = out / "pdfs" / f"{d['doc_id']}.pdf"
            s3.download_file(src["bucket"], d["key"], str(dest))
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            expected = docs[d["doc_id"]]["source_sha256"]
            if digest != expected:
                sys.exit(
                    f"{d['doc_id']}: the PDF in R2 changed since the index was built ({digest[:12]} != {expected[:12]})"
                )
            copied += 1
    print(f"copied {copied} PDFs from R2")


if __name__ == "__main__":
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "_site"
    main(out)
