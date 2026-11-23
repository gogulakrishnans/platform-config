"""Data architecture (same content as data.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.analytics import BigQuery, PubSub
from diagrams.gcp.compute import Run
from diagrams.gcp.database import SQL
from diagrams.gcp.storage import GCS

from _style import CONTROL, DATA, DATAC, DELIVERY, DR, DRC, NONPROD, PROD, SHARED, diagram, legend, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Data architecture", outfile, outformat):
        legend(("DELIVERY", "Bootstrap job applies grants and schemas"), ("DATA", "Contains / data flow"), ("DR", "Replication or copy to DR"), ("CONTROL", "Same customer, related containers"))
        boot = Run("DB bootstrap job (Cloud Run job)\nREVOKE CONNECT/TEMP FROM PUBLIC\nGRANT CONNECT to env login\nCREATE SCHEMA per product")

        with Cluster("data-nonprod · us-east1", graph_attr=NONPROD):
            sqlnp = SQL("sql-nonprod-us-east1-01\n(≤ 40 customers)")
            dbs_np = SQL("acme_corp_dev · _stage · _uat\nbeta_industries_dev · _stage · _uat\nschemas: payment, reporting, …")
            gnp = GCS("pfx-acme-corp-{product}-{env}\nregional, CMEK per group")
            bnp = BigQuery("acme_corp_{product}_{env}")
            tnp = PubSub("acme-corp-{product}-{env}-{name}")

        with Cluster("data-prod · us-east1 (primary)", graph_attr=PROD):
            sqlp = SQL("sql-prod-us-east1-01\nEnterprise Plus · regional HA\n(≤ 25 customers)")
            dbp = SQL("acme_corp_prod\nschemas: payment, reporting\nCONNECT: acme-corp-prod login only")
            gp = GCS("pfx-acme-corp-{product}-prod\ndual-region + turbo\nCMEK key ring location: us")
            bp = BigQuery("acme_corp_{product}_prod")
            tp = PubSub("acme-corp-{product}-prod-*\nstorage: us-east1, us-central1")

        with Cluster("data-prod · us-central1 (DR pair)", graph_attr=DRC):
            sqlr = SQL("sql-prod-us-east1-01-dr\ncross-region DR replica")
            bdr = BigQuery("acme_corp_{product}_prod_dr\ndaily copy (RPO 24 h)")

        with Cluster("data-exchange", graph_attr=SHARED):
            xs = GCS("pfx-acme-corp-shared\n+ acme_corp_shared\nshared reference (all 4 envs read)")
            xd = GCS("pfx-acme-corp-seed\nsanitized dumps, 7-day lifecycle")

        boot >> Edge(**DELIVERY) >> [sqlnp, sqlp]
        sqlnp >> Edge(**DATA) >> dbs_np
        sqlp >> Edge(**DATA) >> dbp
        sqlp >> Edge(label="async, write endpoint\nfollows the primary", **DR) >> sqlr
        bp >> Edge(label="cross-region copy, daily", **DR) >> bdr
        gp - Edge(**CONTROL) - tp
        gnp - Edge(**CONTROL) - bnp - Edge(**CONTROL) - tnp
        dbp >> Edge(label="sanitized seed down", **DATA) >> xd
        xs >> Edge(xlabel="read only", **DATA) >> [dbs_np, dbp]


if __name__ == "__main__":
    main(render, "data-gcp")
