"""Step 2 of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
cut the loaded `Document`s into chunks (LlamaIndex "nodes") small enough to embed and
retrieve one at a time.

Two passes, chosen by file format:

1. **Structure first.** Markdown is split on its headings (`MarkdownNodeParser`), so a
   chunk never straddles two sections. A section that is still too big and is mostly a
   top-level list is cut at item boundaries instead of mid-item. Numbered log entries
   (`done.md`: `- **#47** [data, breadth] — …`) become one piece each, with the number and
   topic tags in metadata as `entry` and `tags`, so an entry is retrieved and cited whole.
   Other items (backlog bullets, design-doc lists) are packed back together up to
   `CHUNK_SIZE`: a bullet usually needs its neighbours for context, so one bullet per
   chunk would lose meaning without gaining precision. CSVs are split one row per chunk, each row written
   as `column: value` lines (empty cells dropped). A row reads as a self-contained record,
   which embeds far better than a bare comma-separated line whose meaning lives in a
   header the chunk can't see. Identifying columns (`ROW_ID_COLUMNS`) go to metadata.
2. **Size cap second.** Any piece still over `CHUNK_SIZE` tokens is split again by
   `SentenceSplitter`, which cuts at paragraph, then sentence boundaries, with
   `CHUNK_OVERLAP` tokens repeated across the cut so a sentence on the boundary isn't lost
   to both halves.

Why 384 tokens: step 3's local embedding model (bge-small) reads at most 512 tokens and
silently drops the rest. The splitter counts with a different tokenizer, and metadata is
embedded alongside the text, so 384 leaves headroom.

Metadata decides what is embedded and what is only carried along. `section` (the heading
trail, e.g. `Pre-registration > M1 — Baseline state conditioning`) and `title` are embedded:
they give a chunk cut from the middle of a long section its context back. `area` and
`format` are excluded from the embedding (they'd add the same words to hundreds of
chunks) but stay on the node for filtering and citing.

    python -m src.llm.research_docs.chunk                          # per-file chunk stats
    python -m src.llm.research_docs.chunk --show docs/done.md -n 3   # print sample chunks
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import statistics

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import BaseNode, MetadataMode, TextNode
from llama_index.core.utils import get_tokenizer

from src.llm.research_docs.load import load_documents

CHUNK_SIZE = 384
CHUNK_OVERLAP = 40
NOT_EMBEDDED = ["area", "format"]
# CSV columns that identify a row (EXPERIMENTS.csv, TRIALS.csv). They move from the row's
# text into its metadata, so every piece of a row the size cap splits still says which
# experiment it belongs to -- and they become filters for later steps.
ROW_ID_COLUMNS = ("module", "cell_id", "trial_id", "experiment_id", "tier", "outcome")
# `- **#47** [data, breadth] — …` (also `- **#16, #17** …`, `#14.5`, untagged entries).
ENTRY = re.compile(r"- \*\*(#[\d.]+(?:, #[\d.]+)*)\*\*(?: \[([^\]]+)\])?")


def _section(node: BaseNode) -> str:
    """Heading trail for a markdown section: its parents' headings plus its own."""
    parents = [h for h in node.metadata.pop("header_path", "").split("/") if h]
    first = node.get_content().split("\n", 1)[0]
    own = first.lstrip("#").strip() if first.startswith("#") else ""
    return " > ".join(parents + ([own] if own else []))


def _markdown_sections(docs: list[Document]) -> list[BaseNode]:
    pieces = []
    for s in MarkdownNodeParser().get_nodes_from_documents(docs):
        s.metadata["section"] = _section(s)
        pieces += _list_items(s) or [s]
    return pieces


def _list_items(section: BaseNode) -> list[TextNode] | None:
    """Cut a list-heavy section at its top-level items (a `- ` line plus everything under
    it): numbered entries one piece each, everything else -- including the text before the
    first item -- packed into pieces of up to `CHUNK_SIZE`. None unless the section is over
    the size cap and at least half its non-blank lines are list items: a design section
    with a few bullets in its prose stays whole."""
    lines = section.get_content().split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith("- ")]
    if not starts or n_tokens(section) <= CHUNK_SIZE:
        return None
    in_items = sum(1 for l in lines[starts[0]:] if l.strip())
    if in_items < sum(1 for l in lines if l.strip()) / 2:
        return None
    bounds = [0] + starts + [len(lines)]
    pieces: list[TextNode] = []
    packing = False  # is pieces[-1] an open pack that unnumbered items may join?
    for a, b in zip(bounds, bounds[1:]):
        text = "\n".join(lines[a:b]).strip()
        if not text:
            continue
        meta = dict(section.metadata)
        if m := ENTRY.match(text):
            meta["entry"] = m.group(1)
            if m.group(2):
                meta["tags"] = m.group(2)
            pieces.append(TextNode(text=text, metadata=meta))
            packing = False
            continue
        merged = TextNode(text=f"{pieces[-1].text}\n{text}", metadata=meta) if packing else None
        if merged is not None and n_tokens(merged) <= CHUNK_SIZE:
            pieces[-1] = merged
        else:
            pieces.append(TextNode(text=text, metadata=meta))
            packing = True
    return pieces


def _csv_rows(doc: Document) -> list[TextNode]:
    rows = []
    for i, row in enumerate(csv.DictReader(io.StringIO(doc.text))):
        filled = {k: v.strip() for k, v in row.items() if v and v.strip()}
        ids = {k: v for k, v in filled.items() if k in ROW_ID_COLUMNS}
        rows.append(TextNode(
            text="\n".join(f"{k}: {v}" for k, v in filled.items() if k not in ids),
            id_=f"{doc.id_}#row{i}",
            metadata={**doc.metadata, "section": f"row {i}", **ids},
        ))
    return rows


def chunk_documents(docs: list[Document]) -> list[BaseNode]:
    pieces: list[BaseNode] = _markdown_sections([d for d in docs if d.metadata["format"] == "md"])
    for d in docs:
        if d.metadata["format"] == "csv":
            pieces += _csv_rows(d)
    for p in pieces:  # set before splitting: the splitter copies these onto every child
        p.excluded_embed_metadata_keys = list(NOT_EMBEDDED)
    return SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)(pieces)


def n_tokens(node: BaseNode) -> int:
    """Tokens the embedding step will see: text plus embedded metadata."""
    return len(get_tokenizer()(node.get_content(metadata_mode=MetadataMode.EMBED)))


def summarize(nodes: list[BaseNode]) -> str:
    by_path: dict[str, list[int]] = {}
    for n in nodes:
        by_path.setdefault(n.metadata["path"], []).append(n_tokens(n))
    lines = [f"{'path':<62} {'chunks':>6} {'median':>6} {'max':>5}"]
    for path, toks in sorted(by_path.items()):
        lines.append(f"{path:<62} {len(toks):>6} {statistics.median(toks):>6.0f} {max(toks):>5}")
    allt = [t for toks in by_path.values() for t in toks]
    lines.append(f"{len(nodes)} chunks; tokens median {statistics.median(allt):.0f}, "
                 f"max {max(allt)}, under 30: {sum(t < 30 for t in allt)}")
    return "\n".join(lines)


def show(nodes: list[BaseNode], path: str, n: int) -> str:
    """The first `n` chunks of one file, exactly as the embedding model will read them."""
    picked = [x for x in nodes if x.metadata["path"] == path][:n]
    return "\n\n".join(
        f"--- chunk {i} ({n_tokens(x)} tokens) ---\n{x.get_content(metadata_mode=MetadataMode.EMBED)}"
        for i, x in enumerate(picked)
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", metavar="PATH", help="print sample chunks of one file")
    ap.add_argument("-n", type=int, default=3)
    args = ap.parse_args()
    nodes = chunk_documents(load_documents())
    print(show(nodes, args.show, args.n) if args.show else summarize(nodes))
