"""Live probes for the isolation tests. Each returns True if the access SUCCEEDED (a breach) and False
if it was denied. Credentials: the isolation-tester identity impersonates the actor's env GSA (it
holds roles/iam.serviceAccountTokenCreator on env GSAs only, and nothing else).
Skeleton: the calls are written out; they are exercised against a real environment.
"""
from __future__ import annotations


def _creds(actor_gsa: str):
    import google.auth
    from google.auth import impersonated_credentials

    source, _ = google.auth.default()
    return impersonated_credentials.Credentials(
        source_credentials=source, target_principal=actor_gsa,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"], lifetime=600)


def _denied(fn) -> bool:
    from google.api_core import exceptions

    try:
        fn()
    except (exceptions.PermissionDenied, exceptions.Forbidden, exceptions.NotFound, exceptions.Unauthenticated):
        return False
    return True


def probe(case, actor_gsa: str) -> bool:
    creds = _creds(actor_gsa)
    if case.kind == "bucket":
        from google.cloud import storage
        return _denied(lambda: list(storage.Client(credentials=creds).bucket(case.resource).list_blobs(max_results=1)))
    if case.kind == "dataset":
        from google.cloud import bigquery
        project = case.resource.split(".")[0]
        return _denied(lambda: list(bigquery.Client(project=project, credentials=creds)
                                    .query(f"SELECT 1 FROM `{case.resource}.INFORMATION_SCHEMA.TABLES` LIMIT 1").result()))
    if case.kind == "topic":
        from google.cloud import pubsub_v1
        return _denied(lambda: pubsub_v1.PublisherClient(credentials=creds).publish(case.resource, b"isolation-test").result(30))
    if case.kind == "key":
        from google.cloud import kms
        return _denied(lambda: kms.KeyManagementServiceClient(credentials=creds).encrypt(name=case.resource, plaintext=b"x"))
    if case.kind in ("database", "schema"):
        from google.cloud.sql.connector import Connector, IPTypes
        instance, db = case.resource.split("/")[0], case.resource.split("/")[-1].split(".")[0]
        user = actor_gsa.removesuffix(".gserviceaccount.com")

        def connect():
            with Connector(credentials=creds, ip_type=IPTypes.PRIVATE) as c:
                conn = c.connect(instance, "pg8000", user=user, db=db, enable_iam_auth=True)
                if case.kind == "schema":
                    conn.cursor().execute(f'SELECT 1 FROM information_schema.tables WHERE table_schema = %s', (case.resource.split(".")[1],))
                conn.close()
        return _denied(connect)
    if case.kind == "namespace":
        # The actor's KSA token is exchanged on the target cluster; RBAC + AppProject + NetworkPolicy deny it.
        raise NotImplementedError("namespace probe runs as a Job in the actor's namespace (rollout)")
    raise ValueError(case.kind)
