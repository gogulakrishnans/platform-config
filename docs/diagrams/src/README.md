# Diagrams with Google Cloud icons

Diagram-as-code sources for every diagram in `docs/diagrams/`, drawn with the
[`diagrams`](https://diagrams.mingrammer.com/docs/nodes/gcp) library and the official Google Cloud
product icons. Each Mermaid page (`docs/diagrams/<name>.md`) links to its icon version, which has the
same content.

| Source | Output | Mirrors |
|---|---|---|
| [gke.py](gke.py) | `gke-gcp.svg` / `.png` | [gke.md](../gke.md) (D2) |
| [cloud_run.py](cloud_run.py) | `cloud-run-gcp.svg` / `.png` | [cloud-run.md](../cloud-run.md) (D2) |
| [instance_group.py](instance_group.py) | `instance-group-gcp.svg` / `.png` | [instance-group.md](../instance-group.md) (D2) |
| [hierarchy.py](hierarchy.py) | `hierarchy-gcp.svg` / `.png` | [hierarchy.md](../hierarchy.md) |
| [regions.py](regions.py) | `regions-gcp.svg` / `.png` | [regions.md](../regions.md) |
| [data.py](data.py) | `data-gcp.svg` / `.png` | [data.md](../data.md) |
| [data_sharing.py](data_sharing.py) | `data-sharing-gcp.svg` / `.png` | [data-sharing.md](../data-sharing.md) |
| [network_security.py](network_security.py) | `network-security-gcp.svg` / `.png` | [network-security.md](../network-security.md) |
| [ha_dr.py](ha_dr.py) | `ha-dr-gcp.svg` / `.png` | [ha-dr.md](../ha-dr.md) |
| [multi_product.py](multi_product.py) | `multi-product-gcp.svg` / `.png` | [multi-product.md](../multi-product.md) |
| [runners.py](runners.py) | `runners-gcp.svg` / `.png` | [runners.md](../runners.md) |

All diagrams share [_style.py](_style.py): fonts (18 pt labels, 22 pt cluster titles), colours
(red prod, blue non-prod, orange DR, green data, purple shared/exchange) and edge styles (purple
dashed = delivery, blue = traffic, green = data access, orange dashed = DR/replication, grey dotted =
policy and keys). The SVGs embed their icons, so they render anywhere; open them in a browser and zoom.

## Render

```bash
# Graphviz is required: winget install Graphviz.Graphviz | apt-get install graphviz | brew install graphviz
python -m venv .venv && .venv/bin/pip install -r docs/diagrams/src/requirements.txt
.venv/bin/python docs/diagrams/src/render_all.py              # all diagrams, SVG + PNG
.venv/bin/python docs/diagrams/src/render_all.py gke data     # selected ones
```

When a diagram's content changes, update both the Mermaid page and its `.py` source in the same PR.
`scripts/render-diagrams.py --check` (repo gate) fails if any icon diagram's SVG or PNG is missing.
