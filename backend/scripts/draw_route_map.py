"""
Poster coverage map: every route over a light street map, colored by surface.
Run after export_route_map.py (needs matplotlib: pip3 install matplotlib).
    python3 scripts/draw_route_map.py
Writes scripts/audit_output/route_coverage_map.png (300 dpi) and .pdf
"""
import json
import math
import os
import pickle
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "audit_output", "route_map_data.json")
NETWORK = os.path.join(HERE, ".shade_cache", "network.pkl")
OUT = os.path.join(HERE, "audit_output", "route_coverage_map")
OXY = (-118.2108, 34.1270)
COLORS = {"pavement": "#2563EB", "trail": "#16A34A", "mixed": "#F59E0B", "track": "#DC2626"}
LABELS = {"pavement": "Road", "trail": "Trail", "mixed": "Road + trail", "track": "Track"}

routes = json.load(open(sys.argv[1] if len(sys.argv) > 1 else DATA))
xs = sorted(p[0] for r in routes for p in r["coords"])
ys = sorted(p[1] for r in routes for p in r["coords"])
# frame the bulk of the routes (ignore a few far-flung ones)
q = lambda s, f: s[int(f * (len(s) - 1))]
x0, x1, y0, y1 = q(xs, .01), q(xs, .99), q(ys, .01), q(ys, .99)
padx, pady = (x1 - x0) * .04, (y1 - y0) * .04
x0, x1, y0, y1 = x0 - padx, x1 + padx, y0 - pady, y1 + pady
aspect = 1 / math.cos(math.radians((y0 + y1) / 2))

PLACES = [  # (name, lon, lat) for orientation
    ("Pasadena", -118.140, 34.150), ("Glendale", -118.255, 34.150), ("Burbank", -118.315, 34.185),
    ("Griffith Park", -118.296, 34.130), ("Highland Park", -118.192, 34.108), ("Silver Lake", -118.270, 34.087),
    ("Downtown LA", -118.248, 34.048), ("Alhambra", -118.130, 34.092), ("South Pasadena", -118.155, 34.120),
    ("La Cañada Flintridge", -118.185, 34.228), ("Angeles National Forest", -118.150, 34.262),
]
RINGS_MI = [3, 6]


def miles(a, b):
    kx = 69.17 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 69.0)


fig, ax = plt.subplots(figsize=(12, 12 * (y1 - y0) * aspect / (x1 - x0)))
fig.patch.set_facecolor("white")
ax.set_facecolor("#FBFCFD")
if os.path.exists(NETWORK):
    d = pickle.load(open(NETWORK, "rb"))
    segs = [c for *_, c in d["edges"] if any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in c[:: max(1, len(c) // 3)])]
    ax.add_collection(LineCollection(segs, colors="#E6E9EE", linewidths=0.2, zorder=1))
for surf in ["pavement", "mixed", "track", "trail"]:
    segs = [r["coords"] for r in routes if (r["surface"] or "pavement") == surf]
    ax.add_collection(LineCollection(segs, colors=COLORS[surf], linewidths=0.7, alpha=0.45, zorder=2))

# distance rings around Oxy, labeled with how many routes start inside
import matplotlib.patheffects as pe
halo = [pe.withStroke(linewidth=3.5, foreground="white")]
for r_mi in RINGS_MI:
    n_in = sum(1 for r in routes if miles(r["coords"][0], OXY) <= r_mi)
    t = [i * 2 * math.pi / 240 for i in range(241)]
    ax.plot([OXY[0] + r_mi / (69.17 * math.cos(math.radians(OXY[1]))) * math.cos(a) for a in t],
            [OXY[1] + r_mi / 69.0 * math.sin(a) for a in t],
            color="#111827", lw=1.3, ls=(0, (5, 4)), alpha=0.7, zorder=4)
    ax.text(OXY[0], OXY[1] + r_mi / 69.0 + (y1 - y0) * .006, f"{r_mi} mi from Oxy: {n_in} routes start inside",
            ha="center", va="bottom", fontsize=11, fontweight="bold", color="#111827", zorder=6, path_effects=halo)

for name, lon, lat in PLACES:
    if x0 < lon < x1 and y0 < lat < y1:
        ax.text(lon, lat, name, ha="center", va="center", fontsize=11, color="#334155",
                fontstyle="italic", zorder=5, path_effects=halo)
ax.plot(*OXY, marker="*", markersize=24, color="#111827", markeredgecolor="white", markeredgewidth=1.5, zorder=7)
ax.annotate("Occidental College", OXY, xytext=(12, -16), textcoords="offset points", fontsize=13,
            fontweight="bold", color="#111827", zorder=7, path_effects=halo)

counts = {s: sum(1 for r in routes if (r["surface"] or "pavement") == s) for s in COLORS}
handles = [Line2D([], [], color=COLORS[s], lw=4, label=f"{LABELS[s]}: {counts[s]}") for s in COLORS if counts[s]]
leg = ax.legend(handles=handles, loc="lower left", fontsize=12, frameon=True, framealpha=0.95,
                title="Route surface", title_fontsize=12, borderpad=0.8)
leg.get_frame().set_edgecolor("#CBD5E1")
ax.set_title(f"{len(routes):,} running routes across Northeast LA", fontsize=20, fontweight="bold",
             color="#111827", loc="left", pad=26)
share6 = sum(1 for r in routes if miles(r["coords"][0], OXY) <= RINGS_MI[-1]) / len(routes)
ax.text(0, 1.012, f"Each line is one route, built from OpenStreetMap streets and trails. "
        f"{share6:.0%} start within {RINGS_MI[-1]} miles of campus.", transform=ax.transAxes, fontsize=12, color="#475569")

# scale bar: 2 miles
km2deg = 1 / (111.32 * math.cos(math.radians((y0 + y1) / 2)))
bx, by = x1 - (x1 - x0) * .05 - 3.219 * km2deg, y0 + (y1 - y0) * .04
ax.plot([bx, bx + 3.219 * km2deg], [by, by], color="#111827", lw=3, zorder=5)
ax.text(bx + 1.61 * km2deg, by + (y1 - y0) * .012, "2 mi", ha="center", fontsize=11, zorder=5, path_effects=halo)
ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect(aspect)
ax.set_xticks([]); ax.set_yticks([])
for sp in ax.spines.values():
    sp.set_edgecolor("#CBD5E1")
ax.text(0.995, 0.003, "Streets: © OpenStreetMap contributors", transform=ax.transAxes,
        ha="right", va="bottom", fontsize=8, color="#64748B")
plt.savefig(OUT + ".png", dpi=300, bbox_inches="tight", pad_inches=0.05)
plt.savefig(OUT + ".pdf", bbox_inches="tight", pad_inches=0.05)
print(f"Saved {OUT}.png and .pdf")
