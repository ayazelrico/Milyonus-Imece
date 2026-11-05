# Web quotas and validation

Each model call, including tool iterations, reserves monthly usage atomically
before contacting the provider. Independent SQLite connections serialize with
BEGIN IMMEDIATE. Successful calls refund the difference from reported usage;
failed, interrupted and unreported calls retain their reservation. Process
restarts therefore cannot release potentially billable work accidentally.

Configuration:

- `MILYONUS_WEB_MONTHLY_TOKENS`: monthly token allowance, default 5000000.
- `MILYONUS_WEB_MONTHLY_USD`: monthly estimated USD ceiling; default 0 disables it.
- `MILYONUS_WEB_INPUT_USD_PER_MILLION` and
  `MILYONUS_WEB_OUTPUT_USD_PER_MILLION`: explicit model prices. Both must be
  positive when the USD ceiling is enabled. No model price is guessed.

Input reservations use a generous serialized byte estimate plus framing,
rather than a provider-specific tokenizer. Provider overhead or pricing can
differ. This is an admission ceiling on estimates, not a guaranteed invoice
ceiling. Actual usage above the reservation is recorded and blocks subsequent
calls. Unknown-usage charges remain conservative. Retries consume new capacity.

The regression test launches 200 attempts through independent connections on
16 threads and admits exactly ten reservations under a ten-reservation quota.
This is a local database concurrency test, not production load acceptance.

For a deployed test environment, set `MILYONUS_LOAD_COOKIE` to a dedicated test
account's Cookie header without committing it, then run:

```sh
python scripts/web_load.py --url https://YOUR-TEST-HOST --requests 1000 \
  --concurrency 20 --out experiments/web-api-load.json
```

The probe performs only authenticated usage reads and fails on HTTP errors or
p95 above 1.5 seconds. It does not establish model first-token latency. W7 still
requires full streaming turn tests against the intended deployment/provider.

External beta requires 20 real participants and recorded outcomes. No outreach
was sent. No deployed test URL, test session cookie, SMTP credentials or model
API credentials were present in this session's environment. Docker was absent.
These missing dependencies prevent production validation and billed 5X runs;
they must not be replaced with fabricated results or synthetic beta users.
