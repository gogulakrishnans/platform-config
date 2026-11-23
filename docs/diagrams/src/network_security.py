"""Network and security layers (same content as network-security.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.compute import BinaryAuthorization
from diagrams.gcp.database import SQL
from diagrams.gcp.network import NAT, PSC, Armor, FirewallRules, LoadBalancing, ServiceMesh
from diagrams.gcp.operations import Logging
from diagrams.gcp.security import IAP, KMS, AccessContextManager, Iam, SecurityCommandCenter
from diagrams.onprem.client import Users
from diagrams.onprem.network import Internet

from _style import CONTROL, DATAC, GREY, NONPROD, PLAIN, PROD, SHARED, TRAFFIC, diagram, legend, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Network and security layers", outfile, outformat, nodesep="1.5", ranksep="2.5"):
        legend(("TRAFFIC", "Request path through the layers"), ("CONTROL", "Governs / feeds detection"))
        inet = Internet("Internet")
        ops = Users("Operators")

        with Cluster("1 · Edge", graph_attr=PROD):
            armor = Armor("Cloud Armor\nDDoS · OWASP CRS · geo · bot\nrate limit per IP + customer")
            lb = LoadBalancing("Global external ALB\nTLS 1.2+ · Certificate Manager")
            iap = IAP("IAP\noperators, dev/stage, SSH")

        with Cluster("2 · Network (vpc-prod / vpc-nonprod, never peered)", graph_attr=NONPROD):
            fwh = FirewallRules("hierarchical firewall\ndeny internet ingress except\nGFE, health checks, IAP")
            fwt = FirewallRules("VPC firewall by tag t-{customer}-{env}\ndefault deny between tenants")
            nat = NAT("Cloud NAT, static IPs\negress allowlist")
            pga = PSC("Private Google Access / PSC")
            vpcsc = AccessContextManager("VPC-SC perimeters\nnon-prod · prod · exchange")

        with Cluster("3 · Workload", graph_attr=PLAIN):
            mesh = ServiceMesh("Istio mTLS STRICT · AuthorizationPolicy\nSidecar · NetworkPolicy default deny\negress gateway · JWT")
            binauthz = BinaryAuthorization("Binary Authorization (promoted)\nscan blocks CRITICAL/HIGH\nPSS restricted · Shielded nodes")

        with Cluster("4 · Identity", graph_attr=SHARED):
            wif = Iam("WIF for GKE (KSA principal)\nenv GSA per customer per env")
            iam = Iam("resource-level IAM only\nno SA keys · tokens ≤ 1 h")

        with Cluster("5 · Data", graph_attr=DATAC):
            db = SQL("Cloud SQL: CONNECT per env login\nPUBLIC revoked")
            cmek = KMS("per-customer CMEK\n(GCS, BQ, PD, Pub/Sub)\n+ app envelope encryption")

        with Cluster("6 · Detect and respond", graph_attr=GREY):
            logs = Logging("Audit Logs → central sink\n(BigQuery + SIEM)")
            scc = SecurityCommandCenter("SCC · Falco · alerts\nisolation tests")

        inet >> Edge(**TRAFFIC) >> armor >> Edge(**TRAFFIC) >> lb >> Edge(**TRAFFIC) >> fwh
        ops >> Edge(**TRAFFIC) >> iap >> Edge(**TRAFFIC) >> fwh
        fwh >> Edge(**TRAFFIC) >> fwt >> Edge(**TRAFFIC) >> mesh >> Edge(**TRAFFIC) >> binauthz
        binauthz >> Edge(**TRAFFIC) >> wif >> Edge(**TRAFFIC) >> iam >> Edge(**TRAFFIC) >> [db, cmek]
        mesh >> Edge(label="egress", **TRAFFIC) >> nat
        pga - Edge(**CONTROL) - iam
        vpcsc - Edge(**CONTROL) - pga
        [db, cmek] >> Edge(**CONTROL) >> logs >> Edge(**CONTROL) >> scc


if __name__ == "__main__":
    main(render, "network-security-gcp")
