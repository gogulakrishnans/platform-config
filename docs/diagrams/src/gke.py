"""GKE deployment architecture (D2) with Google Cloud icons.

Same content as docs/diagrams/gke.md (Mermaid): one region (us-east1) with its DR pair (us-central1)
and the two example customers. Rendered by scripts/render-diagrams.py into docs/diagrams/gke-gcp.svg.
"""
from diagrams import Cluster, Diagram, Edge, Node
from diagrams.gcp.compute import GKE, BinaryAuthorization
from diagrams.gcp.database import SQL
from diagrams.gcp.devtools import GCR
from diagrams.gcp.network import CDN, DNS, NAT, Armor, LoadBalancing, ServiceMesh
from diagrams.gcp.security import IAP, KMS, CertificateManager
from diagrams.gcp.storage import GCS
from diagrams.k8s.compute import Pod
from diagrams.k8s.network import NetworkPolicy
from diagrams.k8s.rbac import ServiceAccount
from diagrams.onprem.client import Users
from diagrams.onprem.gitops import Argocd
from diagrams.onprem.network import Internet
from diagrams.onprem.vcs import Github

# Edge labels: the library sets 13 pt on every Edge, so the font is part of each edge style.
EFONT = dict(fontsize="18", fontname="Arial", fontcolor="#37474f")
# Colours: delivery, user traffic, data, failover / DR, egress.
DELIVERY = dict(color="#7b1fa2", style="dashed", **EFONT)
TRAFFIC = dict(color="#1565c0", style="bold", **EFONT)
DATA = dict(color="#2e7d32", **EFONT)
DR = dict(color="#ef6c00", style="dashed", **EFONT)
EGRESS = dict(color="#616161", **EFONT)

# Text sizes are chosen for reading the PNG at 100% zoom (and on a GitHub page) without zooming in.
FONT = "Arial"
TEXT = "#202124"
CLUSTER_FONT = {"fontsize": "22", "fontname": f"{FONT} Bold", "fontcolor": TEXT}
PROD = {"bgcolor": "#fdecea", "pencolor": "#c62828", "penwidth": "2", **CLUSTER_FONT}
NONPROD = {"bgcolor": "#e8f0fe", "pencolor": "#1a73e8", "penwidth": "2", **CLUSTER_FONT}
DRC = {"bgcolor": "#fff3e0", "pencolor": "#ef6c00", "penwidth": "2", **CLUSTER_FONT}
DATAC = {"bgcolor": "#e6f4ea", "pencolor": "#2e7d32", "penwidth": "2", **CLUSTER_FONT}
NS = {"bgcolor": "#ffffff", "pencolor": "#757575", "style": "dashed", "fontsize": "19",
      "fontname": FONT, "fontcolor": TEXT}

graph_attr = {
    "fontsize": "34",
    "fontname": f"{FONT} Bold",
    "fontcolor": TEXT,
    "labelloc": "t",
    "pad": "0.6",
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
node_attr = {"fontsize": "18", "fontname": FONT, "fontcolor": TEXT, "imagepos": "tc"}
Node._height = 2.2
edge_attr = {"fontsize": "17", "fontname": FONT, "fontcolor": "#37474f", "penwidth": "2", "arrowsize": "1.2"}


def render(outfile: str, outformat: str = "png") -> None:
    with Diagram("GKE deployment architecture", filename=outfile, outformat=outformat, show=False,
                 direction="LR", graph_attr=graph_attr, node_attr=node_attr, edge_attr=edge_attr):
        users = Users("Customer users\n(internet)")
        testers = Users("Customer UAT users\n(allowlisted IPs)")
        ops = Users("Operators")
        saas = Internet("Allowlisted\nexternal APIs")

        with Cluster("Git: platform-config", graph_attr={"bgcolor": "#f5f5f5", "pencolor": "#616161", **CLUSTER_FONT}):
            git = Github("customers/ · products/\nhelm/ · argocd/generated/")

        with Cluster("platform-nonprod  (non-prod perimeter)", graph_attr=NONPROD):
            argo_np = Argocd("ArgoCD Dev/Stage\n+ ArgoCD UAT")
            ar_np = GCR("Artifact Registry\nnon-prod (build)")

        with Cluster("platform-prod  (prod perimeter)", graph_attr=PROD):
            argo_p = Argocd("ArgoCD Prod\ncreate/update only")
            ar_p = GCR("Artifact Registry prod\npromoted by digest")
            binauthz = BinaryAuthorization("Binary Authorization\n(promoted attestation)")

        with Cluster("compute-devstage · devstage-us-east1-01 · RAPID · private", graph_attr=NONPROD):
            iap = IAP("IAP")
            ilb = LoadBalancing("Internal ALB\n*.dev|stage.platform.internal")
            gke_ds = GKE("devstage cluster")
            with Cluster("namespaces (tenant chart)", graph_attr=NS):
                ns_dev = Pod("acme-corp-dev")
                ns_stg = Pod("acme-corp-stage")

        with Cluster("compute-uat · uat-us-east1-01 · REGULAR", graph_attr=NONPROD):
            armor_u = Armor("Cloud Armor\nIP allowlist")
            glb_u = LoadBalancing("Global ALB\n*.uat.platform.example")
            gke_u = GKE("uat cluster")
            ns_uat = Pod("acme-corp-uat\nbeta-industries-uat")

        with Cluster("compute-prod · global edge (L2-edge)", graph_attr=PROD):
            dns = DNS("Cloud DNS\nacme-corp.platform.example")
            armor_p = Armor("Cloud Armor\nWAF · rate limits")
            glb_p = LoadBalancing("Global external ALB")
            cdn = CDN("Cloud CDN")
            certs = CertificateManager("Certificate Manager\napex + wildcard")

        with Cluster("compute-prod · prod-us-east1-01 · STABLE · 3 zones", graph_attr=PROD):
            gke_p = GKE("prod cluster")
            igw = ServiceMesh("Istio ingress gateway\nJWT + customer claim")
            with Cluster("ns acme-corp-prod", graph_attr=NS):
                pod_a = Pod("payment-api\nRollout (canary)")
                ksa = ServiceAccount("KSA payment\n(Workload Identity)")
                netpol = NetworkPolicy("default deny\n+ Sidecar scope")
            with Cluster("ns beta-industries-prod", graph_attr=NS):
                pod_b = Pod("product pods")
            egw = ServiceMesh("Istio egress gateway\nServiceEntry allowlist")
            nat = NAT("Cloud NAT\nstatic IPs")

        with Cluster("compute-prod · prod-us-east1-01-dr (us-central1)", graph_attr=DRC):
            gke_dr = GKE("DR cluster\nminimum replicas")
            ns_dr = Pod("acme-corp-prod\nbeta-industries-prod")

        with Cluster("data-prod (customer containers)", graph_attr=DATAC):
            sql = SQL("sql-prod-us-east1-01\nEnterprise Plus HA\nacme_corp_prod → schema payment")
            sql_dr = SQL("DR replica\n(us-central1)")
            gcs = GCS("pfx-acme-corp-payment-prod\ndual-region, CMEK")

        with Cluster("security-prod", graph_attr=DATAC):
            kms = KMS("kr-acme-corp-prod\nus-east1 · us-central1 · us")

        # User traffic
        users >> Edge(**TRAFFIC) >> dns
        users >> Edge(**TRAFFIC) >> armor_p >> Edge(**TRAFFIC) >> glb_p
        glb_p - Edge(color="#9e9e9e", style="dotted") - cdn
        glb_p - Edge(color="#9e9e9e", style="dotted") - certs
        glb_p >> Edge(label="NEG", **TRAFFIC) >> igw >> Edge(**TRAFFIC) >> pod_a
        glb_p >> Edge(xlabel="DR NEG: capacity 0\nuntil drActive", **DR) >> ns_dr
        testers >> Edge(**TRAFFIC) >> armor_u >> Edge(**TRAFFIC) >> glb_u >> Edge(**TRAFFIC) >> ns_uat
        ops >> Edge(**TRAFFIC) >> iap >> Edge(**TRAFFIC) >> ilb >> Edge(**TRAFFIC) >> [ns_dev, ns_stg]

        # Delivery (GitOps)
        git >> Edge(label="GitOps index", **DELIVERY) >> [argo_np, argo_p]
        argo_np >> Edge(xlabel="DNS endpoint + IAM", **DELIVERY) >> gke_u
        argo_np >> Edge(**DELIVERY) >> gke_ds
        argo_p >> Edge(label="tenant + product\nApplicationSets", **DELIVERY) >> gke_p
        argo_p >> Edge(xlabel="DR target", **DELIVERY) >> gke_dr
        ar_np >> Edge(label="copy by digest", **DELIVERY) >> ar_p
        ar_p >> Edge(**DELIVERY) >> binauthz >> Edge(**DELIVERY) >> gke_p

        # Workloads inside the clusters
        gke_ds - Edge(color="#bdbdbd", style="invis") - ns_dev
        gke_u - Edge(color="#bdbdbd") - ns_uat
        gke_p - Edge(color="#bdbdbd") - igw
        gke_dr - Edge(color="#bdbdbd") - ns_dr
        pod_a - Edge(color="#bdbdbd", style="dotted") - ksa
        pod_a - Edge(color="#bdbdbd", style="dotted") - netpol
        igw >> Edge(**TRAFFIC) >> pod_b

        # Identity and data
        ksa >> Edge(label="WIF → bucket IAM", **DATA) >> gcs
        ksa >> Edge(label="Auth Proxy, IAM login\nCONNECT own DB only", **DATA) >> sql
        sql >> Edge(label="async replication", **DR) >> sql_dr
        sql >> Edge(label="CMEK", style="dotted", color="#2e7d32", **EFONT) >> kms
        gcs >> Edge(style="dotted", color="#2e7d32", **EFONT) >> kms

        # Egress
        pod_a >> Edge(**EGRESS) >> egw >> Edge(**EGRESS) >> nat >> Edge(**EGRESS) >> saas


def embed_icons(svg_path: str) -> None:
    """Make the SVG self-contained: the library links icons by local file path, so inline each one
    as a data URI. The result renders the same on GitHub, in a browser, or on another machine."""
    import base64
    import mimetypes
    import re
    from pathlib import Path

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


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "gke-gcp"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "svg"
    render(out, fmt)
    if fmt == "svg":
        embed_icons(f"{out}.svg")
