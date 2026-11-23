"""GKE deployment architecture (D2) with Google Cloud icons.

Same content as docs/diagrams/gke.md (Mermaid): one region (us-east1) with its DR pair (us-central1)
and the two example customers.  Render: python docs/diagrams/src/render_all.py (or this file).
"""
from diagrams import Cluster, Edge
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

from _style import CONTROL, DATA, DATAC, DELIVERY, DR, DRC, EGRESS, GREY, LINK, NONPROD, NS, PROD, TRAFFIC, diagram, main


def render(outfile: str, outformat: str) -> None:
    with diagram("GKE deployment architecture", outfile, outformat):
        users = Users("Customer users\n(internet)")
        testers = Users("Customer UAT users\n(allowlisted IPs)")
        ops = Users("Operators")
        saas = Internet("Allowlisted\nexternal APIs")

        with Cluster("Git: platform-config", graph_attr=GREY):
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
        glb_p - Edge(**CONTROL) - cdn
        glb_p - Edge(**CONTROL) - certs
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
        gke_ds - Edge(style="invis") - ns_dev
        gke_u - Edge(**LINK) - ns_uat
        gke_p - Edge(**LINK) - igw
        gke_dr - Edge(**LINK) - ns_dr
        pod_a - Edge(**CONTROL) - ksa
        pod_a - Edge(**CONTROL) - netpol
        igw >> Edge(**TRAFFIC) >> pod_b

        # Identity and data
        ksa >> Edge(label="WIF → bucket IAM", **DATA) >> gcs
        ksa >> Edge(label="Auth Proxy, IAM login\nCONNECT own DB only", **DATA) >> sql
        sql >> Edge(label="async replication", **DR) >> sql_dr
        sql >> Edge(label="CMEK", **CONTROL) >> kms
        gcs >> Edge(**CONTROL) >> kms

        # Egress
        pod_a >> Edge(**EGRESS) >> egw >> Edge(**EGRESS) >> nat >> Edge(**EGRESS) >> saas


if __name__ == "__main__":
    main(render, "gke-gcp")
