"""M16 -- Rules as linear filters: the kernel-space scan (DESIGN.md, lines
~854-865; EXPLORATION_LOG.md, 2026-09-24). Track A -- run via
`python -m src.signals.moving_averages.kernel_space_scan`; regenerates
`output/moving_averages/m16_kernel_table.csv`, `m16_similarity_matrix.csv`,
`m16_kernel_space.png` on rerun (gitignored per this repo's own `output/`
convention, same as `feature_sweep.py`/`distance_slope_surface.py`).
"""

import pandas as pd

from src.signals.moving_averages.modules import linear_filter_diagnostic as lfd
from src.signals.moving_averages.stats import kernel_space as ks

pd.set_option("display.width", 160)
pd.set_option("display.max_rows", 50)

rules = lfd.candidate_rules()
table = lfd.kernel_table(rules).sort_values("centroid").reset_index(drop=True)
print("=== Kernel table (centroid, dispersion) ===")
print(table.to_string())

vectors = lfd.weight_vectors(rules)
sim = ks.similarity_matrix(vectors)

for threshold in (0.99, 0.95, 0.90, 0.80):
    clusters = ks.cluster_by_threshold(sim, threshold=threshold)
    n_clusters = len(set(clusters.values()))
    print(f"\n=== threshold={threshold}: {n_clusters} clusters ===")
    from collections import defaultdict

    groups = defaultdict(list)
    for name, cid in clusters.items():
        groups[cid].append(name)
    for cid, names in sorted(groups.items()):
        print(f"  cluster {cid}: {names}")

print("\n=== Similarity of specific pairs DESIGN predicts should be close ===")
pairs = [
    ("dist_pct_sma_200", "slope_log_21_sma_200"),
    ("crossover_sma_50_sma_200", "slope_log_21_sma_200"),
    ("dist_pct_sma_20", "dist_pct_sma_50"),
    ("dist_pct_sma_20", "mom_1_0"),
    ("mom_12_1", "dist_pct_sma_200"),
]
for a, b in pairs:
    print(f"  {a} vs {b}: {sim.loc[a, b]:.4f}")

table.to_csv("output/moving_averages/m16_kernel_table.csv", index=False)
sim.to_csv("output/moving_averages/m16_similarity_matrix.csv")
print("\nWrote output/moving_averages/m16_kernel_table.csv and m16_similarity_matrix.csv")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(16, 7))
kind_color = {"dist_pct": "tab:blue", "slope_log_21": "tab:orange", "mom": "tab:green", "crossover": "tab:red"}
for _, row in table.iterrows():
    name = row["name"]
    kind = next((k for k in kind_color if name.startswith(k)), "other")
    axes[0].scatter(row["centroid"], row["dispersion"], color=kind_color.get(kind, "gray"), s=40)
    axes[0].annotate(name, (row["centroid"], row["dispersion"]), fontsize=6, rotation=20)
axes[0].set_xlabel("centroid (effective lookback, days)")
axes[0].set_ylabel("dispersion (effective smoothing width, days)")
axes[0].set_title("M16: kernel shape by rule (centroid vs. dispersion)")

im = axes[1].imshow(sim.to_numpy(dtype=float), vmin=0, vmax=1, cmap="viridis")
axes[1].set_xticks(range(len(sim)))
axes[1].set_yticks(range(len(sim)))
axes[1].set_xticklabels(sim.columns, fontsize=5, rotation=90)
axes[1].set_yticklabels(sim.index, fontsize=5)
axes[1].set_title("Cosine similarity matrix")
fig.colorbar(im, ax=axes[1], fraction=0.046)
plt.tight_layout()
plt.savefig("output/moving_averages/m16_kernel_space.png", dpi=150)
print("Wrote output/moving_averages/m16_kernel_space.png")
