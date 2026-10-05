"""Step 1 of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
load the repo's own docs as LlamaIndex `Document`s.

One `Document` per file, raw text, no splitting. Chunking is step 2, so this step uses
neither `SimpleDirectoryReader`'s markdown reader (it already splits on headings) nor its
CSV reader (it flattens rows). Keeping whole files here lets us see the corpus before
deciding how to cut it.

Each `Document` carries metadata that later steps use to cite sources and filter:
`path` (repo-relative), `area` (which part of the project it belongs to), `format`
(md / csv) and `title` (first `# ` heading, or the file name).

    python -m src.llm.research_docs.load        # print a summary of the corpus
"""

from __future__ import annotations

from pathlib import Path

from llama_index.core import Document

DOCS_ROOT = Path("docs")
EXTENSIONS = (".md", ".csv")

# Top-level folder under docs/ -> area label. Files directly under docs/ are "project".
AREAS = {
    "features/moving-averages": "ma_study",
    "modeling": "modeling",
    "features": "features",
    "decisions": "decisions",
    "ideation": "ideation",
}


def _area(rel: Path) -> str:
    parent = rel.parent.as_posix()
    for prefix, area in AREAS.items():  # longest prefixes first: dict order matters
        if parent == prefix or parent.startswith(prefix + "/"):
            return area
    return "project"


def _title(text: str, rel: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return rel.name


def load_documents(root: Path = DOCS_ROOT) -> list[Document]:
    """Every .md/.csv under `root`, one `Document` each, sorted by path."""
    docs = []
    for path in sorted(p for p in root.rglob("*") if p.suffix in EXTENSIONS):
        rel = Path(root.name) / path.relative_to(root)  # e.g. docs/modeling/LRP.md
        text = path.read_text(encoding="utf-8")
        docs.append(Document(
            text=text,
            id_=rel.as_posix(),  # stable id: re-loading the same file gives the same id
            metadata={
                "path": rel.as_posix(),
                "area": _area(path.relative_to(root)),
                "format": path.suffix.lstrip("."),
                "title": _title(text, rel),
            },
        ))
    return docs


def summarize(docs: list[Document]) -> str:
    lines = [f"{'path':<62} {'area':<10} {'fmt':<4} {'chars':>8}"]
    for d in docs:
        m = d.metadata
        lines.append(f"{m['path']:<62} {m['area']:<10} {m['format']:<4} {len(d.text):>8,}")
    total = sum(len(d.text) for d in docs)
    lines.append(f"{len(docs)} documents, {total:,} chars (~{total // 4:,} tokens)")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(load_documents()))
