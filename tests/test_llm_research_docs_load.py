import pytest

from src.llm.research_docs.load import load_documents


def test_one_document_per_file_with_metadata(tmp_path):
    root = tmp_path / "docs"
    (root / "features" / "moving-averages").mkdir(parents=True)
    (root / "modeling").mkdir()
    (root / "backlog.md").write_text("# Backlog\n\nitems")
    (root / "modeling" / "LRP.md").write_text("intro\n# Least resistance\n")
    (root / "features" / "moving-averages" / "EXPERIMENTS.csv").write_text("a,b\n1,2\n")
    (root / "features" / "notes.txt").write_text("ignored")

    docs = {d.metadata["path"]: d for d in load_documents(root)}

    assert sorted(docs) == [
        "docs/backlog.md",
        "docs/features/moving-averages/EXPERIMENTS.csv",
        "docs/modeling/LRP.md",
    ]
    assert docs["docs/backlog.md"].metadata["area"] == "project"
    assert docs["docs/modeling/LRP.md"].metadata["title"] == "Least resistance"
    csv = docs["docs/features/moving-averages/EXPERIMENTS.csv"]
    assert csv.metadata == {
        "path": "docs/features/moving-averages/EXPERIMENTS.csv",
        "area": "ma_study", "format": "csv", "title": "EXPERIMENTS.csv",
    }
    assert csv.text == "a,b\n1,2\n"  # raw text, no splitting
    assert csv.id_ == "docs/features/moving-averages/EXPERIMENTS.csv"


def test_missing_root_raises_instead_of_loading_nothing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_documents(tmp_path / "docs")
