"""Instance Group (MIG) deployment architecture (D2) with Google Cloud icons.

Same content as docs/diagrams/instance-group.md: legacy-billing for beta-industries in us-central1
with its DR copy in us-east1, golden images from Packer and configuration from Ansible.
"""
from diagrams import Cluster, Edge
from diagrams.gcp.compute import ComputeEngine
from diagrams.gcp.database import SQL
from diagrams.gcp.network import NAT, Armor, FirewallRules, LoadBalancing
from diagrams.gcp.security import Iam
from diagrams.gcp.storage import GCS, Storage
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users
from diagrams.onprem.iac import Ansible
from diagrams.onprem.vcs import Github

from _style import CONTROL, DATA, DATAC, DELIVERY, DR, DRC, EGRESS, GREY, NONPROD, PROD, TRAFFIC, diagram, legend, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Instance Group (MIG) deployment architecture", outfile, outformat):
        legend("TRAFFIC", ("DELIVERY", "Delivery: image build, promotion, rolling update, Ansible"), "DATA", ("DR", "DR backend (failover)"), ("EGRESS", "Outbound via Cloud NAT"), ("CONTROL", "Identity or firewall policy attached"))
        users = Users("Customer users\n(internet)")

        with Cluster("Git", graph_attr=GREY):
            pins = Github("customers/beta-industries/products.yaml\nlegacy-billing prod: 3.3.2")
            pk = Github("packer/ · ansible/")

        with Cluster("platform-nonprod · non-prod pool", graph_attr=NONPROD):
            packer = GithubActions("Packer build\nhardened base + app\nShielded VM")
            img_np = Storage("image family legacy-billing\n(trusted image project)")
            ans_np = Ansible("Ansible runners (non-prod)\nIAP-only SSH, no public IP")

        with Cluster("platform-prod · prod pool", graph_attr=PROD):
            promo = GithubActions("promotion\ncopy image, record in\nreleases.yaml")
            img_p = Storage("prod image family\nlegacy-billing")
            roll = GithubActions("l4-delivery: MIG step\nnew template → rolling update\nmaxUnavailable 0 · canary 10 %")
            ans_p = Ansible("Ansible runners (prod)\ninventory by labels\ncustomer=beta-industries")

        with Cluster("compute-prod · global edge (L2-edge)", graph_attr=PROD):
            armor = Armor("Cloud Armor\nWAF · rate limits")
            glb = LoadBalancing("Global external ALB\nbeta-industries.platform.example")
            bes = LoadBalancing("backend service\nbeta-industries-billing-prod\nhealth check, draining, TLS")

        with Cluster("compute-prod · us-central1 (primary)", graph_attr=PROD):
            mig = ComputeEngine("regional MIG\nbeta-industries-billing-prod\n3 zones · autohealing · autoscaling")
            ident = Iam("GSA beta-industries-prod\ntag t-beta-industries-prod")
            fw = FirewallRules("VPC firewall, default deny\nLB + health checks → tag\nAnsible → tag :22 only")

        with Cluster("compute-prod · us-east1 (DR copy)", graph_attr=DRC):
            mig_dr = ComputeEngine("MIG (DR)\nsame image, minimum size\nscaled on failover")

        with Cluster("Non-prod (compute-devstage / compute-uat)", graph_attr=NONPROD):
            mig_np = ComputeEngine("beta-industries-billing-\ndev | stage | uat\nnon-prod image family")

        with Cluster("data-prod / data-exchange", graph_attr=DATAC):
            sql = SQL("sql-prod-us-central1-01\nbeta_industries_prod → schema billing\nAuth Proxy on VM, IAM login")
            gcs = GCS("pfx-beta-industries-billing-prod\ndual-region + turbo")
            shared = GCS("pfx-beta-industries-shared\nread-only mount")

        nat = NAT("Cloud NAT")

        # Image pipeline and delivery
        pk >> Edge(**DELIVERY) >> packer >> Edge(**DELIVERY) >> img_np
        img_np >> Edge(label="promoter, read only\nacross perimeters", **DELIVERY) >> promo >> Edge(**DELIVERY) >> img_p
        pins >> Edge(label="pin changed", **DELIVERY) >> roll
        img_p >> Edge(**DELIVERY) >> roll
        roll >> Edge(label="new instance template", **DELIVERY) >> mig
        roll >> Edge(xlabel="same image", **DELIVERY) >> mig_dr
        img_np >> Edge(**DELIVERY) >> mig_np
        ans_np >> Edge(xlabel="config + migrations", **DELIVERY) >> mig_np
        ans_p >> Edge(label="1. migration (expand)\n2. configuration", **DELIVERY) >> mig

        # Traffic
        users >> Edge(**TRAFFIC) >> armor >> Edge(**TRAFFIC) >> glb >> Edge(**TRAFFIC) >> bes >> Edge(**TRAFFIC) >> mig
        bes >> Edge(xlabel="failover backend", **DR) >> mig_dr

        # Identity, policy, data
        mig - Edge(**CONTROL) - ident
        mig - Edge(**CONTROL) - fw
        mig >> Edge(label="IAM DB login", **DATA) >> sql
        mig >> Edge(**DATA) >> gcs
        mig >> Edge(**DATA) >> shared
        mig >> Edge(**EGRESS) >> nat


if __name__ == "__main__":
    main(render, "instance-group-gcp")
