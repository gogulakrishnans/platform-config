"""Shared CI and Ansible runners (same content as runners.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.compute import ComputeEngine
from diagrams.gcp.devtools import GCR
from diagrams.gcp.network import NAT
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.iac import Ansible
from diagrams.onprem.vcs import Github, Git

from _style import CONTROL, DELIVERY, EGRESS, GREY, NONPROD, PROD, TRAFFIC, diagram, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Shared CI and Ansible runners", outfile, outformat, direction="TB", nodesep="2.2"):
        with Cluster("Source", graph_attr=GREY):
            gh = Github("GitHub: platform-config\n+ product repos")
            bb = Git("Bitbucket: product repos")
            fork = Github("fork PRs (public repo)")
        hosted = GithubActions("GitHub-hosted runners\noffline checks, no secrets")

        with Cluster("platform-nonprod · non-prod perimeter", graph_attr=NONPROD):
            ghnp = GithubActions("GitHub ARC pool (non-prod)\nTF L2/L3 non-prod · placement\nimage builds · Packer")
            bbnp = GithubActions("Bitbucket runner pool\nbuild · scan · sign · push")
            ansnp = Ansible("Ansible runners (non-prod)\nOS Login · IAP-only SSH")
            arnp = GCR("AR non-prod")
            m1 = ComputeEngine("non-prod MIGs\n(private IP)")

        with Cluster("platform-prod · prod perimeter", graph_attr=PROD):
            ghp = GithubActions("GitHub ARC pool (prod)\nTF L1 (extra approval) · L2/L3 prod\npromotion · Cloud Run/MIG deploy")
            ansp = Ansible("Ansible runners (prod)")
            arp = GCR("AR prod (multi-region)")
            m2 = ComputeEngine("prod MIGs\n(private IP)")

        nat = NAT("Cloud NAT →\ngithub.com / bitbucket.org")

        fork >> Edge(label="offline checks only", **TRAFFIC) >> hosted
        gh >> Edge(label="protected branch + Environments\nOIDC → WIF", **DELIVERY) >> [ghnp, ghp]
        bb >> Edge(label="Bitbucket OIDC → WIF", **DELIVERY) >> bbnp
        [ghnp, bbnp] >> Edge(**DELIVERY) >> arnp
        arnp >> Edge(label="promote by digest\n(only cross-perimeter read)", **DELIVERY) >> ghp >> Edge(**DELIVERY) >> arp
        ansnp >> Edge(**DELIVERY) >> m1
        ansp >> Edge(**DELIVERY) >> m2
        [ghnp, bbnp, ghp] >> Edge(**EGRESS) >> nat
        ghnp - Edge(style="invis") - ansnp
        ghp - Edge(style="invis") - ansp


if __name__ == "__main__":
    main(render, "runners-gcp")
