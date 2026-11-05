# ADR-0011 — Web erasure vs hash-chained ledger

## Status

Accepted (2026-11-03)

## Context

KVKK/GDPR right to erasure collides with an append-only, tamper-evident ledger.

## Decision

- The audit ledger stores **hashes and actions, not memory content**.
- `DELETE /v1/account` tombstones memory rows (`state='erased'`, content nulled)
  while the chain remains verifiable.
- `GET /v1/export` returns sessions + memory + provenance as JSON before erasure.
- Erasure is irreversible and documented in the UI.

## Consequences

- Users can delete personal content without breaking audit integrity.
- Forensic reconstruction of erased content from the ledger is intentionally impossible.
