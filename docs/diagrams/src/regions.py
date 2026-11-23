"""Region model and placement (same content as regions.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.compute import GKE
from diagrams.gcp.database import SQL
from diagrams.gcp.network import VPC
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.iac import Terraform
from diagrams.onprem.vcs import Github

from _style import DATA, DELIVERY, DR, DRC, GREY, NONPROD, PLAIN, PROD, TRAFFIC, diagram, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Region model and placement", outfile, outformat):
        pr = Github("New customer PR\nregion.primary: us-east1")

        with Cluster("Git (read only by placement)", graph_attr=GREY):
            reg = Github("inventory/regions.yaml\nstatus · drPair · cidr · quotas")
            inv = Github("inventory/clusters, sql\n(written by L2)")
            cust = Github("customers/*/customer.yaml\n+ products.yaml, catalog")

        job = GithubActions("Placement job\n1. region active?\n2. cell with most headroom\n3. DBs in the same region\n4. Cloud Run quota (primary + DR)\n5. write placement")

        commit = Github("bot commit to customer.yaml\ndevstage: devstage-us-east1-02\nuat: uat-us-east1-01\nprod: prod-us-east1-01 (+ -dr)")
        fail = Github("PR check fails:\nregion not provisioned")
        cap = Terraform("capacity PR (new cell)\nor quota PR\nplatform approval → L2 apply")

        with Cluster("us-east1 (active) ↔ DR pair us-central1", graph_attr=PLAIN):
            with Cluster("non-prod cells", graph_attr=NONPROD):
                c1 = GKE("devstage-us-east1-01, -02\n40 customers each")
                c2 = GKE("uat-us-east1-01 (40)")
            with Cluster("prod cell", graph_attr=PROD):
                c3 = GKE("prod-us-east1-01 (25)")
                s3 = SQL("sql-prod-us-east1-01")
            with Cluster("DR (located in us-central1)", graph_attr=DRC):
                c3dr = GKE("prod-us-east1-01-dr")
                s3dr = SQL("sql-prod-us-east1-01-dr")

        with Cluster("europe-west1 (reserved) ↔ europe-west4", graph_attr=GREY):
            eu = VPC("IP ranges reserved\nnothing created until a platform PR")

        pr >> Edge(**DELIVERY) >> job
        [reg, inv, cust] >> Edge(**DATA) >> job
        job >> Edge(label="headroom OK", **TRAFFIC) >> commit >> Edge(**TRAFFIC) >> [c1, c2, c3]
        job >> Edge(xlabel="region not active", **DR) >> fail
        job >> Edge(xlabel="no headroom / quota", **DR) >> cap
        c3 >> Edge(label="DR pair", **DR) >> c3dr
        s3 >> Edge(label="replica", **DR) >> s3dr
        c3 - Edge(**DATA) - s3
        eu - Edge(style="invis") - c1


if __name__ == "__main__":
    main(render, "regions-gcp")
