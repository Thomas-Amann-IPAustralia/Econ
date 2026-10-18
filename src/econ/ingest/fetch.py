"""Stage `fetch`: copy the corpus from the R2 bucket to data/raw, and reconcile it with config/sources.yaml.

Identity is the R2 object key. An object without a registry entry, or an entry without an object, fails
the run: the owner decides what enters the knowledge base.
"""

from __future__ import annotations

import os

from econ import config
from econ.manifest import Run, StageError, sha256_file


def r2_client():
    import boto3  # build extra

    missing = [
        k for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY") if not os.environ.get(k)
    ]
    if missing:
        raise StageError(f"missing R2 credentials in the environment: {', '.join(missing)}")
    src = config.sources()
    return boto3.client(
        "s3",
        endpoint_url=src.endpoint.format(account_id=os.environ["R2_ACCOUNT_ID"]),
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def fetch(run: Run) -> None:
    src = config.sources()
    raw = config.path(config.pipeline().paths.raw)
    raw.mkdir(parents=True, exist_ok=True)
    s3 = r2_client()

    objects = {}
    token = None
    while True:
        kw = {"Bucket": src.bucket, **({"ContinuationToken": token} if token else {})}
        page = s3.list_objects_v2(**kw)
        for o in page.get("Contents", []):
            objects[o["Key"]] = o
        if not page.get("IsTruncated"):
            break
        token = page["NextContinuationToken"]

    registry = src.by_key()
    unknown = sorted(set(objects) - set(registry))
    absent = sorted(set(registry) - set(objects))
    if unknown:
        raise StageError(
            f"{len(unknown)} object(s) in R2 have no entry in config/sources.yaml", item=unknown[0]
        )
    if absent:
        raise StageError(f"{len(absent)} registry entr(ies) have no object in R2", item=absent[0])

    downloaded = 0
    for key in sorted(objects):
        doc = registry[key]
        dest = raw / f"{doc.doc_id}.pdf"
        etag = objects[key]["ETag"].strip('"')
        stamp = dest.with_suffix(".etag")
        if not (dest.exists() and stamp.exists() and stamp.read_text() == etag):
            tmp = dest.with_suffix(".part")
            s3.download_file(src.bucket, key, str(tmp))
            tmp.replace(dest)
            stamp.write_text(etag)
            downloaded += 1
        run.inputs[f"r2://{src.bucket}/{key}"] = etag
        run.outputs[f"{config.pipeline().paths.raw}/{doc.doc_id}.pdf"] = sha256_file(dest)
    run.counts.update(
        objects=len(objects), downloaded=downloaded, bytes=sum(o["Size"] for o in objects.values())
    )
