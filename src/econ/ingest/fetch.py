"""Stage `fetch`: copy the corpus from the R2 bucket to data/raw, and reconcile it with config/sources.yaml.

Identity is the R2 object key. An object without a registry entry, or an entry without an object, fails
the run: the owner decides what enters the knowledge base. Each corpus (D-033) owns a folder of the bucket
(`r2_prefix`); the original corpus owns the root, less the other corpora's folders. An object the registry
lists as deferred is acknowledged and not fetched.
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


def owned(keys, prefix: str, others: list[str]) -> list[str]:
    """The keys a corpus owns: those under its folder, or for the root corpus, those under no other's."""
    if prefix:
        return [k for k in keys if k.startswith(prefix)]
    return [k for k in keys if not any(o and k.startswith(o) for o in others)]


def fetch(run: Run) -> None:
    src = config.sources()
    corpus = config.corpus()
    others = [c.r2_prefix for n, c in config.pipeline().corpora.items() if n != config.corpus_name()]
    raw = config.path(config.pipeline().paths.raw)
    raw.mkdir(parents=True, exist_ok=True)
    s3 = r2_client()

    listed = {}
    token = None
    while True:
        kw = {
            "Bucket": src.bucket,
            **({"Prefix": corpus.r2_prefix} if corpus.r2_prefix else {}),
            **({"ContinuationToken": token} if token else {}),
        }
        page = s3.list_objects_v2(**kw)
        for o in page.get("Contents", []):
            if not o["Key"].endswith("/"):  # a folder marker is not an object of the corpus
                listed[o["Key"]] = o
        if not page.get("IsTruncated"):
            break
        token = page["NextContinuationToken"]
    deferred = {d.key for d in src.deferred}
    objects = {k: listed[k] for k in owned(listed, corpus.r2_prefix, others) if k not in deferred}

    registry = src.by_key()
    unknown = sorted(set(objects) - set(registry))
    absent = sorted(set(registry) - set(objects))
    if unknown:
        # Every unregistered object goes in the manifest, so the registry entries can be written from it.
        run.params["unregistered"] = [{"key": k, "bytes": objects[k]["Size"]} for k in unknown]
        raise StageError(
            f"{len(unknown)} object(s) in R2 have no entry in config/{corpus.sources}", item=unknown[0]
        )
    if absent:
        raise StageError(f"{len(absent)} registry entr(ies) have no object in R2", item=absent[0])
    run.counts["deferred"] = len(deferred & set(listed))

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
