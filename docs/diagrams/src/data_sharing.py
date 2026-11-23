"""Data-sharing flows inside one customer (same content as data-sharing.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.compute import Run
from diagrams.gcp.database import SQL
from diagrams.gcp.storage import GCS
from diagrams.onprem.ci import GithubActions
from diagrams.gcp.operations import Monitoring
from diagrams.gcp.security import Iam

from _style import DATA, DELIVERY, DR, NONPROD, PROD, SHARED, TRAFFIC, diagram, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Data-sharing flows (one customer)", outfile, outformat):
        with Cluster("Non-prod perimeter", graph_attr=NONPROD):
            dev = SQL("acme-corp dev")
            stage = SQL("acme-corp stage")
            uat = SQL("acme-corp uat")
            imp = Run("import job (data-nonprod)\ndrop + recreate acme_corp_uat\nimport AS target login\nrerun bootstrap")

        with Cluster("Exchange perimeter (data-exchange)", graph_attr=SHARED):
            shared = GCS("pfx-acme-corp-shared\nacme_corp_shared")
            seed = GCS("pfx-acme-corp-seed\nsanitized dumps")

        with Cluster("Prod perimeter", graph_attr=PROD):
            prod = SQL("acme-corp prod\nacme_corp_prod")
            promo = GithubActions("promote pipeline\n(promoter, prod pool)\napproval per step")
            with Cluster("Seed down (data-prod)", graph_attr=PROD):
                s1 = SQL("1-2. export prod DB\n→ scratch instance\n(prod perimeter)")
                s3 = SQL("3. sanitize → verify\n→ _clone_metadata")
                s4 = Iam("4-5. role mapping\n(REASSIGN OWNED),\nexport, delete scratch")
            stop = Monitoring("alert + stop\n(verification failed)")

        # Shared reference
        promo >> Edge(label="write after approval", **DELIVERY) >> shared
        shared >> Edge(xlabel="read only", **DATA) >> [dev, stage, uat, prod]
        # Promote up
        dev >> Edge(label="export package", **DELIVERY) >> stage >> Edge(label="approval", **DELIVERY) >> uat
        uat >> Edge(label="approval (customer-success)", **DELIVERY) >> promo >> Edge(**DELIVERY) >> prod
        # Seed down
        prod >> Edge(**TRAFFIC) >> s1 >> Edge(**TRAFFIC) >> s3 >> Edge(**TRAFFIC) >> s4
        s4 >> Edge(label="write seed dumps only", **TRAFFIC) >> seed
        seed >> Edge(label="non-prod identity pulls", **TRAFFIC) >> imp >> Edge(**TRAFFIC) >> uat
        imp >> Edge(xlabel="if a seedDown target", **TRAFFIC) >> stage
        s3 >> Edge(xlabel="verification fails", **DR) >> stop


if __name__ == "__main__":
    main(render, "data-sharing-gcp")
