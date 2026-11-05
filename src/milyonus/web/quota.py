"""Reserve monthly usage before every provider call, including tool iterations."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict

from milyonus.web.store import WebStore


class QuotaProvider:
    def __init__(self, provider, store: WebStore, tenant_id: str):
        self.provider = provider
        self.store = store
        self.tenant_id = tenant_id
        self.name, self.model = provider.name, provider.model
        self.token_limit = int(os.getenv("MILYONUS_WEB_MONTHLY_TOKENS", "5000000"))
        self.cost_limit = float(os.getenv("MILYONUS_WEB_MONTHLY_USD", "0"))
        self.input_price = float(os.getenv("MILYONUS_WEB_INPUT_USD_PER_MILLION", "0"))
        self.output_price = float(os.getenv("MILYONUS_WEB_OUTPUT_USD_PER_MILLION", "0"))
        prices = (self.cost_limit, self.input_price, self.output_price)
        if self.token_limit <= 0 or any(not math.isfinite(p) or p < 0 for p in prices):
            raise ValueError("invalid web quota configuration")
        if self.cost_limit and (not self.input_price or not self.output_price):
            raise ValueError("cost quota requires explicit input and output prices")
        self.cost_usd = 0.0

    async def stream(self, request):
        # Deliberately generous estimate including provider framing. Actual
        # tokenizer/hidden provider overhead can differ; retain any overage.
        inputs = 4096 + 2 * len(json.dumps(asdict(request), ensure_ascii=False).encode())
        outputs = request.max_output_tokens
        reserved = inputs + outputs
        cost = (inputs * self.input_price + outputs * self.output_price) / 1_000_000
        period = self.store.reserve_quota(
            self.tenant_id,
            tokens=reserved,
            cost=cost,
            token_limit=self.token_limit,
            cost_limit=self.cost_limit,
        )
        used_in = used_out = 0
        got_usage = completed = False
        try:
            async for event in self.provider.stream(request):
                if event.kind == "usage" and event.usage is not None:
                    used_in = max(used_in, event.usage.input_tokens)
                    used_out = max(used_out, event.usage.output_tokens)
                    got_usage = True
                if event.kind == "done":
                    completed = True
                yield event
        finally:
            # Cancellation, missing usage, and errors retain the reservation:
            # the remote service might still bill the request.
            if completed and got_usage:
                actual = (used_in * self.input_price + used_out * self.output_price) / 1_000_000
                self.store.refund_quota(
                    self.tenant_id,
                    period=period,
                    tokens=max(0, reserved - used_in - used_out),
                    cost=max(0, cost - actual),
                )
                if used_in + used_out > reserved or actual > cost:
                    self.store.bump_quota(
                        self.tenant_id,
                        tokens=max(0, used_in + used_out - reserved),
                        cost=max(0, actual - cost),
                    )
                self.cost_usd += actual
            else:
                self.cost_usd += cost
