"""The Global Innovation Index's economy profiles, read from WIPO's own data file (D-033).

The GII report prints one profile page per economy: about 110 scores, values and ranks in two columns,
with strength and weakness symbols. A layout parser reads those pages as wide tables whose rows mix two
pillars, and a chunk of one carries no economy name. WIPO publishes the same numbers in a spreadsheet
(`wipo-pub-2000-2026-tech1.xlsx`). This module writes each profile page's numbers as sentences from that
spreadsheet: one element per economy for its headline figures and one per sub-pillar, each starting with
the economy's name, placed on the economy's profile page so a citation still leads to the printed page.

Numbers are rounded as the printed profile rounds them (one decimal place); a pillar, sub-pillar or
`Score` indicator gives its score, a `Value` indicator its value. Deterministic: no model calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PILLAR = re.compile(r"^(IN|OUT)\.\d$")
_MARKS = re.compile(r"[*†]+$")


@dataclass(frozen=True)
class Node:
    num: str
    name: str
    level: str  # Index, SubIndex, Pillar, SubPillar, Indicator
    profile: str | None  # Score or Value, for an indicator


@dataclass(frozen=True)
class Economy:
    iso3: str
    name: str
    income: str
    region: str
    pop_thousands: float | None
    gdp_ppp_bn: float | None
    gdp_pc_ppp: float | None


@dataclass
class Workbook:
    nodes: list[Node]
    economies: list[Economy]
    data: dict[tuple[str, str], dict]  # (iso3, num) -> the Data sheet's row; num "" is the GII itself


def _rows(ws) -> list[dict]:
    it = ws.iter_rows(values_only=True)
    head = [str(h).strip() if h is not None else "" for h in next(it)]
    return [dict(zip(head, r, strict=False)) for r in it if any(v is not None for v in r)]


def load(path: Path) -> Workbook:
    import openpyxl  # build extra

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    nodes = [
        Node(str(r["NUM"] or ""), str(r["NAME"]).strip(), str(r["LEVEL_TYPE"]), r.get("PROFILE"))
        for r in _rows(wb["Index Structure"])
    ]
    economies = [
        Economy(
            r["ISO3"],
            str(r["ECONOMY_NAME"]).strip(),
            str(r["INCOME_GRP"]),
            str(r["SUBREG_UN"]),
            r["POP"],
            r["PPPGDP"],
            r["PPPPC"],
        )
        for r in _rows(wb["Economies"])
    ]
    data = {(r["ISO3"], str(r["NUM"] or "")): r for r in _rows(wb["Data"])}
    return Workbook(nodes, economies, data)


def _num(x: float | None, places: int = 1) -> str:
    return "n/a" if x is None else f"{x:,.{places}f}"


def _rank(r) -> str:
    return "n/a" if r is None else str(int(r))


def _name(node: Node) -> str:
    return _MARKS.sub("", node.name).strip()


def _flags(row: dict) -> str:
    out = []
    sw = row.get("SW_OVERALL")
    if sw == "S":
        out.append("a strength")
    elif sw == "W":
        out.append("a weakness")
    if row.get("OUTDATED"):
        out.append(f"outdated data, {row['DATAYR']}" if row.get("DATAYR") else "outdated data")
    return f" ({'; '.join(out)})" if out else ""


def _figure(node: Node, row: dict | None) -> str:
    if row is None:
        return f"{_name(node)}: n/a"
    use_value = node.level == "Indicator" and node.profile == "Value"
    v = row.get("VALUE_SCREEN") if use_value else row.get("SCORE")
    what = "" if node.level == "Indicator" else "score "
    return f"{_name(node)}: {what}{_num(v)}, rank {_rank(row.get('RANK'))}{_flags(row)}"


def headline(wb: Workbook, e: Economy, total: int, year: int) -> str:
    g = wb.data.get((e.iso3, ""), {})
    i = wb.data.get((e.iso3, "IN"), {})
    o = wb.data.get((e.iso3, "OUT"), {})
    pop = None if e.pop_thousands is None else e.pop_thousands / 1000
    return (
        f"{e.name}: Global Innovation Index {year} economy profile. {e.name} ranks "
        f"{_rank(g.get('RANK'))} of {total} economies in the GII {year} (score {_num(g.get('SCORE'))}): "
        f"{_rank(i.get('RANK'))} on innovation inputs (score {_num(i.get('SCORE'))}) and "
        f"{_rank(o.get('RANK'))} on innovation outputs (score {_num(o.get('SCORE'))}). "
        f"Income group: {e.income}. Region: {e.region}. Population {_num(pop)} million; "
        f"GDP {_num(e.gdp_ppp_bn)} billion PPP$; GDP per capita {_num(e.gdp_pc_ppp, 0)} PPP$."
    )


def pillar_texts(wb: Workbook, e: Economy, year: int) -> list[str]:
    """One paragraph per sub-pillar, with its indicators, each naming the economy and its pillar, so any
    chunk of them says whose figures they are."""
    out, pillar, cur = [], "", None
    for node in wb.nodes:
        if node.level in ("Index", "SubIndex"):
            continue
        row = wb.data.get((e.iso3, node.num))
        label = node.num.split(".", 1)[1]
        if node.level == "Pillar":
            pillar = f"pillar {label}, {_figure(node, row)}"
        elif node.level == "SubPillar":
            if cur:
                out.append(cur)
            cur = f"{e.name}, GII {year} {pillar}. {label} {_figure(node, row)}."
        else:
            cur += f" {label} {_figure(node, row)}."
    if cur:
        out.append(cur)
    return out


def profile_pages(pdf: Path, economies: list[Economy], search: range) -> dict[str, int]:
    """Each economy's profile page (1-based): a page that prints the profile header ("Output rank",
    "Input rank") and the economy's name (the longest economy name on the page, so "Niger" never claims
    Nigeria's page). The profiles run on consecutive pages, so a profile off that run (the reading guide's
    example) is skipped. Fails unless every economy has exactly one page."""
    import pypdfium2 as pdfium  # build extra

    doc = pdfium.PdfDocument(str(pdf))
    names = sorted(economies, key=lambda e: -len(e.name))
    found: dict[str, list[int]] = {}
    for p in search:
        if p - 1 >= len(doc):
            break
        t = " ".join(doc[p - 1].get_textpage().get_text_range().split())
        if "Output rank" not in t or "Input rank" not in t:
            continue
        e = next((e for e in names if " ".join(e.name.split()) in t), None)
        if e is not None:
            found.setdefault(e.iso3, []).append(p)
    run = sorted(p for ps in found.values() for p in ps)
    # The longest stretch of consecutive pages is the profiles section.
    best, start = (0, 0), 0
    for i in range(1, len(run) + 1):
        if i == len(run) or run[i] != run[i - 1] + 1:
            best = max(best, (i - start, start))
            start = i
    section = set(run[best[1] : best[1] + best[0]])
    out = {}
    for e in economies:
        ps = [p for p in found.get(e.iso3, []) if p in section]
        if len(ps) != 1:
            raise ValueError(f"{e.name}: {len(ps)} profile pages")
        out[e.iso3] = ps[0]
    return out


def profile_elements(
    wb: Workbook, pages: dict[str, int], page_sizes: dict[int, dict], doc_id: str, year: int
) -> dict[int, list[dict]]:
    """Elements for each profile page, keyed by page: a heading, the headline, then one per pillar. Each
    element's box is the whole page, since its sentences restate the page's table as a whole."""
    out = {}
    total = len(wb.economies)
    for e in wb.economies:
        p = pages[e.iso3]
        size = page_sizes[p]
        box = [{"page": p, "bbox": [0.0, 0.0, size["width"], size["height"]]}]
        texts = [headline(wb, e, total, year), *pillar_texts(wb, e, year)]
        els = [{"label": "section_header", "text": f"{e.name}: economy profile", "level": 1}]
        els += [{"label": "text", "text": t} for t in texts]
        out[p] = [
            {"doc_id": doc_id, "page": p, "boxes": box, "ocr": False, "source": "data", **el} for el in els
        ]
    return out


def overlay(rows: list[dict], replacement: dict[int, list[dict]]) -> list[dict]:
    """The document's elements with each profile page's parsed elements replaced by the data's, in reading
    order, renumbered."""
    out, done = [], set()
    for r in rows:
        p = r["page"]
        if p in replacement:
            if p not in done:
                out.extend(replacement[p])
                done.add(p)
            continue
        out.append(r)
    for p in sorted(set(replacement) - done):
        raise ValueError(f"profile page {p} has no parsed elements to replace")
    return [{**r, "seq": i} for i, r in enumerate(out)]
