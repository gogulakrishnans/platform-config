"""HA and DR for one prod cell (same content as ha-dr.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.analytics import BigQuery, PubSub
from diagrams.gcp.compute import GKE, ComputeEngine, Run
from diagrams.gcp.database import SQL
from diagrams.gcp.devtools import GCR
from diagrams.gcp.network import LoadBalancing
from diagrams.gcp.security import KMS, SecretManager
from diagrams.gcp.storage import GCS
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Github

from _style import CONTROL, DATA, DR, DRC, GREY, PROD, SHARED, TRAFFIC, diagram, main


def render(outfile: str, outformat: str) -> None:
    with diagram("HA and DR (per prod cell)", outfile, outformat, nodesep="1.7"):
        users = Users("Users")
        glb = LoadBalancing("Global external ALB\nhealth checks per backend")

        with Cluster("us-east1 · prod cell prod-us-east1-01", graph_attr=PROD):
            gke = GKE("GKE regional (3 zones)\nPDBs · topology spread")
            run = Run("Cloud Run (multi-zone)")
            mig = ComputeEngine("regional MIGs\n3 zones, autohealing")
            sql = SQL("sql-prod-us-east1-01\nEnterprise Plus · regional HA")
            bq = BigQuery("BigQuery us-east1")

        with Cluster("us-central1 · DR for this cell", graph_attr=DRC):
            gke_dr = GKE("prod-us-east1-01-dr\nmin replicas\n(full size if hot standby)")
            run_dr = Run("Cloud Run copies\nmin instances 0-1")
            mig_dr = ComputeEngine("MIGs at minimum size")
            sql_dr = SQL("sql-prod-us-east1-01-dr\nDR replica, same size")
            bq_dr = BigQuery("BigQuery us-central1")
            backup = GKE("Backup for GKE (PVCs)\nstored in us-central1")

        with Cluster("Spans both regions", graph_attr=SHARED):
            gcs = GCS("GCS dual-region + turbo\nRPO ≤ 15 min")
            ps = PubSub("Pub/Sub\nstorage: region + pair")
            kms = KMS("KMS keys in both\nregions + us")
            ar = GCR("AR prod multi-region")
            sec = SecretManager("secrets replicated")

        with Cluster("Failover runbook (RTO ~30 min)", graph_attr=GREY):
            rb = Github("1 freeze deploys to the cell\n2 promote-replica --failover\n3 confirm write endpoint\n4 scale DR cluster / MIGs / Cloud Run\n5 drActive PR: shift LB backends\n6 re-point push subscriptions\n7 verify SLOs · failback = switchover")

        users >> Edge(**TRAFFIC) >> glb >> Edge(**TRAFFIC) >> [gke, run, mig]
        glb >> Edge(label="failover (drActive)", **DR) >> [gke_dr, run_dr, mig_dr]
        sql >> Edge(label="async replication\nRPO ~5 min", **DR) >> sql_dr
        bq >> Edge(label="daily copy, RPO 24 h", **DR) >> bq_dr
        [gke, run, mig] >> Edge(**DATA) >> sql
        [gke_dr, run_dr, mig_dr] >> Edge(xlabel="after promote,\nvia write endpoint", **DR) >> sql_dr
        gke >> Edge(**DR) >> backup
        for n in (gcs, ps, kms, ar, sec):
            sql_dr - Edge(style="invis") - n
        rb - Edge(**CONTROL) - sql


if __name__ == "__main__":
    main(render, "ha-dr-gcp")
