# ADR-0010 — Web tenancy isolation (option A)

## Status

Accepted (2026-11-03)

## Context

`MemoryStore.active()` is global on a single-user CLI. A multi-tenant web
surface would leak agent notes across accounts if we share one SQLite file.

## Decision

**Option A for beta:** one data directory per tenant
(`MILYONUS_HOME=/data/t/<tenant_id>`). Each request resolves the tenant from
the session cookie and opens stores under that home. No shared `state.db`.

Option B (`tenant_id` column + Postgres RLS) is deferred until scale requires it.

## Consequences

- Simple and hard to mis-query.
- Slightly more disk and process overhead.
- A CI safety test asserts tenant A's memory never appears in tenant B's snapshot.
