#!/usr/bin/env python3
"""5xx ratio of one tagged Cloud Run revision over the last window (used by cloud-run-canary.sh).

Reads run.googleapis.com/request_count from Cloud Monitoring. Prints a float; "0" with no traffic.
Requires google-cloud-monitoring and the deployer identity (roles/monitoring.viewer).
"""
from __future__ import annotations

import argparse
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--service", required=True)
    ap.add_argument("--region", required=True)
    ap.add_argument("--revision-tag", required=True)
    ap.add_argument("--window", type=int, default=300)
    a = ap.parse_args()

    from google.cloud import monitoring_v3  # imported lazily: needs credentials

    client = monitoring_v3.MetricServiceClient()
    now = int(time.time())
    interval = monitoring_v3.TimeInterval(end_time={"seconds": now}, start_time={"seconds": now - a.window})
    base = (f'metric.type="run.googleapis.com/request_count" AND resource.labels.service_name="{a.service}" '
            f'AND resource.labels.location="{a.region}"')
    total = errors = 0
    for series in client.list_time_series(name=f"projects/{a.project}", filter=base, interval=interval,
                                          view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL):
        if a.revision_tag not in series.resource.labels.get("revision_name", "") and \
           series.metric.labels.get("tag", a.revision_tag) != a.revision_tag:
            continue
        n = sum(p.value.int64_value for p in series.points)
        total += n
        if series.metric.labels.get("response_code_class") == "5xx":
            errors += n
    print(errors / total if total else 0)


if __name__ == "__main__":
    main()
