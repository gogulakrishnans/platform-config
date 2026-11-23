"""Shared look for the Google Cloud icon diagrams (docs/diagrams/src/*.py).

Every diagram uses the same fonts, colours and edge styles, and is written as a self-contained SVG
(icons embedded) plus a PNG. Text sizes are chosen so the PNG is legible at 100 % and the SVG at
any zoom.
"""
from __future__ import annotations

import base64
import mimetypes
import re
import sys
from pathlib import Path

from diagrams import Diagram, Node

FONT = "Arial"
TEXT = "#202124"

# Edge labels: the library sets 13 pt on every Edge, so the font is part of each edge style.
EFONT = dict(fontsize="18", fontname=FONT, fontcolor="#37474f")
DELIVERY = dict(color="#7b1fa2", style="dashed", **EFONT)    # pipelines, GitOps, promotion
TRAFFIC = dict(color="#1565c0", style="bold", **EFONT)       # user and service traffic
DATA = dict(color="#2e7d32", **EFONT)                        # data access
DR = dict(color="#ef6c00", style="dashed", **EFONT)          # replication, failover, DR paths
EGRESS = dict(color="#616161", **EFONT)                      # outbound
CONTROL = dict(color="#455a64", style="dotted", **EFONT)     # policy, keys, relationships
LINK = dict(color="#bdbdbd", **EFONT)                        # "part of"

_CLUSTER_FONT = {"fontsize": "22", "fontname": f"{FONT} Bold", "fontcolor": TEXT}
PROD = {"bgcolor": "#fdecea", "pencolor": "#c62828", "penwidth": "2", **_CLUSTER_FONT}
NONPROD = {"bgcolor": "#e8f0fe", "pencolor": "#1a73e8", "penwidth": "2", **_CLUSTER_FONT}
DRC = {"bgcolor": "#fff3e0", "pencolor": "#ef6c00", "penwidth": "2", **_CLUSTER_FONT}
DATAC = {"bgcolor": "#e6f4ea", "pencolor": "#2e7d32", "penwidth": "2", **_CLUSTER_FONT}
SHARED = {"bgcolor": "#f3e5f5", "pencolor": "#7b1fa2", "penwidth": "2", **_CLUSTER_FONT}
GREY = {"bgcolor": "#f5f5f5", "pencolor": "#616161", "penwidth": "2", **_CLUSTER_FONT}
PLAIN = {"bgcolor": "#ffffff", "pencolor": "#9e9e9e", "penwidth": "2", **_CLUSTER_FONT}
NS = {"bgcolor": "#ffffff", "pencolor": "#757575", "style": "dashed", "fontsize": "19",
      "fontname": FONT, "fontcolor": TEXT}

GRAPH = {
    "fontsize": "34",
    "fontname": f"{FONT} Bold",
    "fontcolor": TEXT,
    "labelloc": "t",
    "pad": "2.0,0.6",     # labels are wider than icons; keep the outermost ones inside the image
    "nodesep": "1.1",
    "ranksep": "1.6",
    "splines": "spline",
    "compound": "true",
    "forcelabels": "true",
    "newrank": "true",
    "dpi": "110",
}
# Icons sit at the top of each node and the label below it; nodes are a little taller than the
# library default so 18 pt labels never overlap the icon.
NODE = {"fontsize": "18", "fontname": FONT, "fontcolor": TEXT, "imagepos": "tc"}
EDGE = {"fontsize": "18", "fontname": FONT, "fontcolor": "#37474f", "penwidth": "2", "arrowsize": "1.2"}
Node._height = 2.2


def diagram(title: str, outfile: str, outformat: str, direction: str = "LR", **graph) -> Diagram:
    return Diagram(title, filename=outfile, outformat=outformat, show=False, direction=direction,
                   graph_attr={**GRAPH, **graph}, node_attr=NODE, edge_attr=EDGE)


def embed_icons(svg_path: str) -> None:
    """The library links icons by local file path; inline each one as a data URI so the SVG renders
    the same on GitHub, in a browser or on another machine."""
    p = Path(svg_path)
    text = p.read_text(encoding="utf-8")

    def inline(m: re.Match) -> str:
        src = Path(m.group(2))
        if not src.exists():
            return m.group(0)
        mime = mimetypes.guess_type(src.name)[0] or "image/png"
        return f'{m.group(1)}="data:{mime};base64,{base64.b64encode(src.read_bytes()).decode()}"'

    text = re.sub(r'(xlink:href|href)="([^"]+\.(?:png|svg))"', inline, text)
    p.write_text(text, encoding="utf-8", newline="\n")


def main(render, default_out: str) -> None:
    """CLI used by every diagram module: <module>.py [outfile-without-extension] [svg|png|both]."""
    out = sys.argv[1] if len(sys.argv) > 1 else default_out
    fmt = sys.argv[2] if len(sys.argv) > 2 else "both"
    for f in (["svg", "png"] if fmt == "both" else [fmt]):
        render(out, f)
        if f == "svg":
            embed_icons(f"{out}.svg")
