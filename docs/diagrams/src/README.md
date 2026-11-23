# Diagrams with Google Cloud icons (prototype)

Diagram-as-code sources using the [`diagrams`](https://diagrams.mingrammer.com/docs/nodes/gcp) library and the
official Google Cloud product icons. The Mermaid diagrams next to this folder remain the reviewed source until
this style is adopted for all three runtime diagrams.

```bash
# Graphviz is required: winget install Graphviz.Graphviz  |  apt-get install graphviz  |  brew install graphviz
python -m venv .venv && .venv/bin/pip install -r docs/diagrams/src/requirements.txt
.venv/bin/python docs/diagrams/src/gke.py docs/diagrams/gke-gcp svg   # self-contained SVG (icons embedded)
.venv/bin/python docs/diagrams/src/gke.py docs/diagrams/gke-gcp png   # PNG
```

| Source | Output | Same content as |
|---|---|---|
| [gke.py](gke.py) | [../gke-gcp.svg](../gke-gcp.svg), [../gke-gcp.png](../gke-gcp.png) | [../gke.md](../gke.md) (Mermaid) |

Text sizes: 18 pt labels, 22 pt cluster titles. Read the SVG in a browser (or on GitHub) and zoom; the PNG is legible at 100 %.
