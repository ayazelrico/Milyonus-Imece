"""Read-only authenticated HTTP load probe; never prints session credentials.

MILYONUS_LOAD_COOKIE contains the Cookie header for a dedicated test account.
This measures API latency, not model first-token latency or full turn capacity.
"""

import argparse
import asyncio
import json
import math
import os
import time
from pathlib import Path

import httpx


async def run(args):
    cookie = os.environ.get("MILYONUS_LOAD_COOKIE")
    if not cookie:
        raise SystemExit("MILYONUS_LOAD_COOKIE is required")
    samples = []
    failures = 0
    gate = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        base_url=args.url, headers={"Cookie": cookie}, timeout=15,
        limits=httpx.Limits(max_connections=args.concurrency),
    ) as client:
        async def request():
            nonlocal failures
            async with gate:
                start = time.perf_counter()
                try:
                    response = await client.get("/v1/usage")
                    if response.status_code != 200:
                        failures += 1
                except httpx.HTTPError:
                    failures += 1
                samples.append(time.perf_counter() - start)

        started = time.perf_counter()
        await asyncio.gather(*(request() for _ in range(args.requests)))
        duration = time.perf_counter() - started
    p95 = sorted(samples)[math.ceil(len(samples) * 0.95) - 1]
    result = {
        "scope": "authenticated usage API only; excludes model/SSE latency",
        "requests": args.requests, "concurrency": args.concurrency,
        "failures": failures, "p95_seconds": p95,
        "requests_per_second": args.requests / duration,
        "passed": failures == 0 and p95 <= args.max_p95,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--max-p95", type=float, default=1.5)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    if min(options.requests, options.concurrency, options.max_p95) <= 0:
        parser.error("requests, concurrency and max-p95 must be positive")
    raise SystemExit(asyncio.run(run(options)))
