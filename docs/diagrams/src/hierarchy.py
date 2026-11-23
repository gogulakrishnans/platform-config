"""Resource hierarchy, projects and VPC-SC perimeters (same content as hierarchy.md)."""
from diagrams import Cluster, Edge
from diagrams.gcp.compute import GKE
from diagrams.gcp.database import SQL
from diagrams.gcp.management import Project
from diagrams.gcp.network import VPC
from diagrams.gcp.security import KMS, ResourceManager, SecurityCommandCenter
from diagrams.gcp.storage import GCS
from diagrams.onprem.gitops import Argocd

from _style import CONTROL, DATAC, DELIVERY, GREY, LINK, NONPROD, PROD, SHARED, TRAFFIC, diagram, main


def render(outfile: str, outformat: str) -> None:
    with diagram("Resource hierarchy, projects and VPC-SC perimeters", outfile, outformat, direction="TB",
                 nodesep="1.8", ranksep="2.0"):
        org = ResourceManager("Organization 000000000000\norg policies: allowed regions, no external IP,\nno SA keys, OS Login, Shielded VM,\ntrusted images, CMEK required")

        with Cluster("Folders", graph_attr=GREY):
            folders = {n: ResourceManager(f"Folder: {n}") for n in ("Network", "Compute", "Data", "Platform", "Security")}
            fded = ResourceManager("Folder: Dedicated\n(opt-in customers)")

        with Cluster("VPC-SC perimeter: non-prod", graph_attr=NONPROD):
            netnp = VPC("net-nonprod\nShared VPC host")
            cds = GKE("compute-devstage\ndevstage cells")
            cu = GKE("compute-uat\nuat cells")
            dnp = SQL("data-nonprod\nnon-prod SQL pool")
            pnp = Argocd("platform-nonprod\nArgoCD Dev/Stage + UAT\nrunners · AR non-prod")
            snp = KMS("security-nonprod\nkey rings · build signer")

        with Cluster("VPC-SC perimeter: prod", graph_attr=PROD):
            netp = VPC("net-prod\nShared VPC host")
            cp = GKE("compute-prod\nprod cells + DR clusters\nglobal LB, certificates")
            dp = SQL("data-prod\nprod SQL + DR replicas\nseed-down function")
            pp = Argocd("platform-prod\nArgoCD Prod\nrunners · AR prod")
            sp = SecurityCommandCenter("security-prod\nkey rings · prod attestor\nlog sinks · SCC")

        with Cluster("VPC-SC perimeter: exchange", graph_attr=SHARED):
            dx = GCS("data-exchange\nper customer: shared bucket,\nshared dataset, seed bucket")

        with Cluster("Opt-in", graph_attr=DATAC):
            dc = Project("{customer}-dedicated\n(project factory)")

        org >> Edge(**LINK) >> list(folders.values()) + [fded]
        folders["Network"] >> Edge(**LINK) >> [netnp, netp]
        folders["Compute"] >> Edge(**LINK) >> [cds, cu, cp]
        folders["Data"] >> Edge(**LINK) >> [dnp, dp, dx]
        folders["Platform"] >> Edge(**LINK) >> [pnp, pp]
        folders["Security"] >> Edge(**LINK) >> [snp, sp]
        fded >> Edge(**LINK) >> dc

        netnp - Edge(xlabel="Shared VPC", **CONTROL) - cds
        netnp - Edge(**CONTROL) - [cu, dnp, pnp]
        netp - Edge(xlabel="Shared VPC", **CONTROL) - cp
        netp - Edge(**CONTROL) - [dp, pp]

        dp >> Edge(label="write seed dumps\npromote shared ref", **TRAFFIC) >> dx
        dnp >> Edge(xlabel="read shared ref\nread seed dumps", **TRAFFIC) >> dx
        pp >> Edge(xlabel="promoter: read AR non-prod only", **DELIVERY) >> pnp


if __name__ == "__main__":
    main(render, "hierarchy-gcp")
