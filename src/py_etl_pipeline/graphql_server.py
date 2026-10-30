"""Strawberry GraphQL ASGI app: operational metadata (no secrets)."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

import strawberry
from starlette.applications import Starlette
from starlette.routing import Route
from strawberry.asgi import GraphQL

from py_etl_pipeline.config import load_batch_size
from py_etl_pipeline.graphql_http import GraphQLHTTPBoundary


def _package_version() -> str:
    try:
        return version("py-etl-pipeline")
    except PackageNotFoundError:
        return "0.1.0"


def _normalised_load_mode() -> str:
    raw = os.getenv("LOAD_MODE", "bulk").strip().lower() or "bulk"
    return raw if raw in ("bulk", "upsert") else "bulk"


@strawberry.type
class EtlRuntimeInfo:
    load_batch_size: int
    default_load_mode: str
    scheduled_default: bool


@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> str:
        return "ok"

    @strawberry.field
    def version(self) -> str:
        return _package_version()

    @strawberry.field
    def etl(self) -> EtlRuntimeInfo:
        sched = os.getenv("RUN_SCHEDULED", "").strip().lower() in ("1", "true", "yes")
        return EtlRuntimeInfo(
            load_batch_size=load_batch_size(),
            default_load_mode=_normalised_load_mode(),
            scheduled_default=sched,
        )


schema = strawberry.Schema(query=Query)


def create_app() -> Starlette:
    """Create a local metadata probe, or expose public metadata by explicit opt-in.

    Configuration uses the process environment only. Export ETL_GRAPHQL_PUBLIC=1
    before startup to permit remote clients; no credentials are accepted or required.
    """
    public = os.getenv("ETL_GRAPHQL_PUBLIC", "0")
    if public not in {"0", "1"}:
        raise ValueError("ETL_GRAPHQL_PUBLIC must be 0 or 1.")
    graphql = GraphQL(
        schema, graphql_ide=None, subscription_protocols=(), multipart_uploads_enabled=False
    )
    endpoint = GraphQLHTTPBoundary(graphql, public_metadata=public == "1")
    application = Starlette(routes=[Route("/graphql", endpoint, methods=["GET", "POST"])])
    application.router.redirect_slashes = False
    return application


app = create_app()
