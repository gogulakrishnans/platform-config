"""Multi-product composition for one customer (same content as multi-product.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.analytics import BigQuery, PubSub
from diagrams.gcp.compute import GKE, ComputeEngine, Run
from diagrams.gcp.database import SQL
from diagrams.gcp.security import Iam
from diagrams.gcp.storage import GCS
from diagrams.k8s.compute import Pod
from diagrams.k8s.group import Namespace
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.iac import Terraform
from diagrams.onprem.gitops import Argocd
from diagrams.onprem.vcs import Github

from _style import DATA, DATAC, DELIVERY, GREY, NONPROD, PROD, SHARED, diagram, legend, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Multi-product composition (acme-corp prod)", outfile, outformat):
        legend(("DELIVERY", "Validation and delivery flow"), ("DATA", "Resources created by L3"))
        with Cluster("Catalog (platform-owned)", graph_attr=SHARED):
            p1 = GKE("payment-api\ngke · sql · bucket · publishes events")
            p2 = Run("reporting-engine\ncloud-run · sql · bucket · bq\nsubscribes payment-events\ndepends on payment-api")
            p3 = ComputeEngine("legacy-billing\nmig · sql · bucket")

        with Cluster("customers/acme-corp/products.yaml", graph_attr=GREY):
            sel = Github("payment-api: dev 2.6.0-beta.1 … prod 2.5.0\nreporting-engine: dev 1.9.0 … prod 1.8.2")

        val = GithubActions("PR validator\ndependencies · runtime rules\nversion window · promoted prod pins")

        l3 = Terraform("L3 composition module (per env)\nlargest size wins · union of resources\noverrides last")
        l4 = Argocd("L4 delivery\nArgoCD · Cloud Run step · MIG step")

        with Cluster("Created by L3 for acme-corp prod", graph_attr=DATAC):
            db = SQL("acme_corp_prod\nschemas payment, reporting")
            b = GCS("pfx-acme-corp-payment-prod\npfx-acme-corp-reporting-prod")
            d = BigQuery("acme_corp_reporting_prod (+ _dr)")
            t = PubSub("acme-corp-payment-prod-events\npush sub → reporting · DLQ")
            crs = Run("Cloud Run service\nacme-corp-reporting-prod (shape)")
            ident = Iam("GSA acme-corp-prod\nIAM per resource · keys")

        with Cluster("Delivered by L4", graph_attr=PROD):
            ns = Namespace("tenant chart: ns acme-corp-prod\n(+ DR cluster)")
            rel = Pod("Helm release payment-api 2.5.0\n(Rollout, by digest)")
            rev = Run("Cloud Run revision 1.8.2\n(traffic split)")

        [p1, p2, p3] >> Edge(**DELIVERY) >> val
        sel >> Edge(**DELIVERY) >> val
        val >> Edge(**DELIVERY) >> [l3, l4]
        l3 >> Edge(**DATA) >> [db, b, d, t, crs, ident]
        l4 >> Edge(**DELIVERY) >> [ns, rel, rev]


if __name__ == "__main__":
    main(render, "multi-product-gcp")
