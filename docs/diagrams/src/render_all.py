"""Render every Google Cloud icon diagram into docs/diagrams/<name>-gcp.{svg,png}.

    python docs/diagrams/src/render_all.py            # all diagrams, SVG + PNG
    python docs/diagrams/src/render_all.py gke data   # selected diagrams

Requires Graphviz and `pip install -r docs/diagrams/src/requirements.txt`.
"""
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
sys.path.insert(0, str(HERE))

from _style import embed_icons  # noqa: E402

# module -> output name (matches the Mermaid page it mirrors: docs/diagrams/<name>.md)
DIAGRAMS = {
    "gke": "gke",
    "cloud_run": "cloud-run",
    "instance_group": "instance-group",
    "hierarchy": "hierarchy",
    "regions": "regions",
    "data": "data",
    "data_sharing": "data-sharing",
    "network_security": "network-security",
    "ha_dr": "ha-dr",
    "multi_product": "multi-product",
    "runners": "runners",
}


def main(selected: list[str]) -> None:
    for module, name in DIAGRAMS.items():
        if selected and module not in selected and name not in selected:
            continue
        mod = importlib.import_module(module)
        out = str(OUT / f"{name}-gcp")
        for fmt in ("svg", "png"):
            mod.render(out, fmt)
        embed_icons(out + ".svg")
        print(f"rendered {name}-gcp.svg, {name}-gcp.png")


if __name__ == "__main__":
    main(sys.argv[1:])
