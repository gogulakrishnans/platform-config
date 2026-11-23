"""Cloud Run deployment architecture (D2) with Google Cloud icons.

Same content as docs/diagrams/cloud-run.md: reporting-engine for acme-corp, a Pub/Sub push
subscriber of payment-api, in us-east1 with its DR copy in us-central1.
"""
from diagrams import Cluster, Edge
from diagrams.gcp.analytics import BigQuery, PubSub
from diagrams.gcp.compute import GKE, BinaryAuthorization, Run
from diagrams.gcp.database import SQL
from diagrams.gcp.devtools import GCR
from diagrams.gcp.network import NAT, Armor, LoadBalancing
from diagrams.gcp.security import IAP, Iam
from diagrams.gcp.storage import GCS
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Github

from _style import CONTROL, DATA, DATAC, DELIVERY, DR, DRC, EGRESS, GREY, NONPROD, PROD, TRAFFIC, diagram, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Cloud Run deployment architecture", outfile, outformat):
        users = Users("Customer users\n(internet)")
        testers = Users("Customer UAT users\n(allowlisted IPs)")
        ops = Users("Operators")

        with Cluster("Git: platform-config", graph_attr=GREY):
            pins = Github("customers/acme-corp/products.yaml\nreporting-engine prod: 1.8.2")

        with Cluster("platform-prod · prod runner pool (WIF, ephemeral)", graph_attr=PROD):
            deploy = GithubActions("l4-delivery: Cloud Run step\nmigrate → revision --no-traffic\n10 → 25 → 50 → 100 %, SLO check")
            ar_p = GCR("Artifact Registry prod\nimage by digest")
            binauthz = BinaryAuthorization("Binary Authorization\n(promoted attestation)")

        with Cluster("Non-prod (compute-devstage / compute-uat)", graph_attr=NONPROD):
            iap = IAP("IAP")
            ilb = LoadBalancing("Dev/Stage internal ALB\nserverless NEG")
            run_dev = Run("acme-corp-reporting-dev\nacme-corp-reporting-stage")
            armor_u = Armor("Cloud Armor\nUAT allowlist")
            glb_u = LoadBalancing("UAT global ALB\nserverless NEG")
            run_uat = Run("acme-corp-reporting-uat")

        with Cluster("compute-prod · global edge (L2-edge)", graph_attr=PROD):
            armor = Armor("Cloud Armor\nWAF · rate limit per host")
            glb = LoadBalancing("Global external ALB\nacme-corp.platform.example\n/v1/reports")

        with Cluster("compute-prod · us-east1 (primary)", graph_attr=PROD):
            svc = Run("acme-corp-reporting-prod\n1.8.2: 90 % · 1.8.3 canary: 10 %\nmin instances ≥ 1")
            job = Run("Cloud Run job\nacme-corp-reporting-prod-migrate")
            ident = Iam("GSA acme-corp-prod\ningress: internal + LB\ninvoker: LB + push SA only")

        with Cluster("compute-prod · us-central1 (DR copy)", graph_attr=DRC):
            svc_dr = Run("acme-corp-reporting-prod\nsame digest, min 0-1\nscaled on failover")

        with Cluster("compute-prod · GKE prod-us-east1-01", graph_attr=PROD):
            pay = GKE("payment-api (acme-corp-prod)\npublisher")

        with Cluster("data-prod (customer containers)", graph_attr=DATAC):
            topic = PubSub("acme-corp-payment-prod-events\nstorage: us-east1 + us-central1, CMEK")
            sub = PubSub("push subscription → reporting\nOIDC token, retry policy")
            dlq = PubSub("dead-letter topic\n…-events-dlq")
            sql = SQL("sql-prod-us-east1-01\nacme_corp_prod → schema reporting")
            bq = BigQuery("acme_corp_reporting_prod\ndaily copy → us-central1")
            gcs = GCS("pfx-acme-corp-reporting-prod\ndual-region + turbo")

        nat = NAT("Cloud NAT")

        # Delivery
        pins >> Edge(label="pin changed", **DELIVERY) >> deploy
        ar_p >> Edge(**DELIVERY) >> deploy
        deploy >> Edge(**DELIVERY) >> binauthz >> Edge(label="tagged revision", **DELIVERY) >> svc
        deploy >> Edge(label="migrate first", **DELIVERY) >> job
        deploy >> Edge(xlabel="same digest", **DELIVERY) >> svc_dr

        # Traffic
        users >> Edge(**TRAFFIC) >> armor >> Edge(**TRAFFIC) >> glb
        glb >> Edge(label="serverless NEG us-east1", **TRAFFIC) >> svc
        glb >> Edge(xlabel="DR NEG (failover)", **DR) >> svc_dr
        ops >> Edge(**TRAFFIC) >> iap >> Edge(**TRAFFIC) >> ilb >> Edge(**TRAFFIC) >> run_dev
        testers >> Edge(**TRAFFIC) >> armor_u >> Edge(**TRAFFIC) >> glb_u >> Edge(**TRAFFIC) >> run_uat

        # Events
        pay >> Edge(label="publish (KSA via WIF)", **TRAFFIC) >> topic >> Edge(**TRAFFIC) >> sub
        sub >> Edge(label="OIDC push", **TRAFFIC) >> svc
        sub >> Edge(xlabel="max delivery attempts", **CONTROL) >> dlq
        sub >> Edge(xlabel="re-pointed on failover", **DR) >> svc_dr

        # Identity and data
        svc - Edge(**CONTROL) - ident
        svc >> Edge(label="connector, IAM login", **DATA) >> sql
        job >> Edge(xlabel="expand / contract", **DATA) >> sql
        svc >> Edge(**DATA) >> bq
        svc >> Edge(**DATA) >> gcs
        svc >> Edge(label="Direct VPC egress", **EGRESS) >> nat


if __name__ == "__main__":
    main(render, "cloud-run-gcp")
