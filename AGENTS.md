# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## What this is

`solaxng` (published on PyPI as `solax-ng`) is a Python library that talks to the local
real-time-data HTTP endpoint exposed by Solax solar inverters (and rebadged/compatible models) and
turns the raw JSON payload into a typed, unit-aware `InverterResponse`. Solax doesn't publish a
stable protocol or a way to identify which inverter model is answering, so the library ships a
schema per known model, probes the request shapes those models declare, and reports every model
whose schema accepts a response — usually one, but ambiguity is surfaced rather than guessed away.

## Commands

This project uses `uv` for dependency management and packaging (`uv_build` backend). Run the full
check suite exactly as CI does via `make verify` (`uv sync`, then black, isort, mypy, flake8,
pylint, pytest). Other targets: `make test`, `make build`, `make publish`, `make clean`. To run
pieces individually:

```sh
uv sync                                     # install/refresh the dev environment
uv run black --check .                      # formatting check (drop --check to auto-format)
uv run isort --profile black .
uv run mypy .
uv run flake8 --ignore=E501,E704 src tests
uv run pylint -d 'C0111' src tests
uv run pytest --cov=solaxng --cov-fail-under=100 --cov-branch --cov-report=term-missing .
```

Run a single test file or case:

```sh
uv run pytest tests/test_solax.py
uv run pytest tests/test_solax.py::test_x1_hybrid_gen4 -v
```

Coverage is enforced at 100% (`--cov-fail-under=100`) — new code needs tests, including error
paths.

`tests/test_schema_ambiguity.py` also doubles as a CLI to rank schema permissiveness, useful when
diagnosing a collision:

```sh
uv run python -m tests.test_schema_ambiguity
```

## Architecture

See `docs/ARCHITECTURE.md` for the full writeup; summary below.

```
src/solaxng/
├── __init__.py              RealTimeAPI + rt_request retry loop
├── discovery.py             Endpoint probing + offline model matching
├── endpoints.py             The request shapes an inverter is known to answer
├── inverter.py              Inverter base class (schema, decoder, lifecycle)
├── inverter_http_client.py  Immutable HTTP request description + transport
├── response_parser.py       Generic envelope schema + per-sensor decoding
├── units.py                 Units / Measurement value types
├── utils.py                 Small decode helpers (packers, scalers, validators)
└── inverters/                One module per supported inverter model
```

Each inverter model is a plugin registered via a `solaxng.inverter` entry point in `pyproject.toml`,
not a hardcoded list — `discovery.py` builds its registry by reading those entry points at import time.
This lets a caller pass `inverters=[...]` to `discover()` and bypass plugin lookup entirely.

**`Inverter` (`inverter.py`)** — base class every model subclasses. Owns `_schema` (a
`voluptuous.Schema` for the exact JSON shape), `response_decoder()` (maps sensor name →
index/packer, `Unit`, post-processors), and serial-number getters. `endpoints` declares which
request shapes the model's firmware answers, defaulting to both query-string and POST-body params
since firmware revisions differ on which one they accept; declaration order decides which endpoint
a matched model is built on. `parse_response()` decodes an already-fetched payload, which is what
lets discovery test one response against many models. `Inverter.sensor_map()` derives `{name: (index, Measurement)}`
from `response_decoder()` — this is a public contract consumed by downstream integrations (see the
"Warning, HA depends on this" comment in `inverter.py`); preserve its shape even when changing the
decoder tuple format.

**`EndpointConfig` (`endpoints.py`)** — frozen, hashable value object naming one way to frame the
request (method, path, params in query vs. body, extra headers, whether a password applies).
`build(host, port, pwd)` turns it into an `InverterHttpClient` and does no I/O. Request shape is a
property of the endpoint, not the model, so models only declare which configs they answer. Being
hashable is what lets discovery key a dict on one and probe it once. `ENDPOINT_REGISTRY` lists the
known shapes, but discovery probes the union of what the in-scope models declare, so a third-party
plugin may define its own.

**`InverterHttpClient` (`inverter_http_client.py`)** — frozen dataclass describing how to talk to
one endpoint (no I/O on construction). `.replace()`-style copy-on-write API, and interns identical
instances via a `WeakValueDictionary` so two descriptions of the same request compare equal by
identity.

**`ResponseParser` (`response_parser.py`)** — validates in two layers: `GENERIC_RESPONSE_SCHEMA`
(every response needs `sn`, `ver`/`version`, `type`, non-empty non-all-zero `data`) combined
(`vol.And`) with the model-specific `_schema`. Then `map_response()` walks
`response_decoder()` to project the raw `data` array into named, unit-converted values via
`utils.py` helpers (`div10`, `to_signed`, `pack_u16`, …), returning an `InverterResponse`
namedtuple.

**Discovery flow (`discovery.py`)** — one inverter is answering and there's no reliable "what model
am I" field, so asking is separated from identifying:
1. `_probe_plan()` groups the in-scope models by declared endpoint into an insertion-ordered
   `{EndpointConfig: [model, …]}`. This is the deduplication: one request shape is one probe
   however many models declare it (16 models, 5 probes for the full registry).
2. Each endpoint is probed once, staggered one second apart to avoid hammering the inverter's
   embedded HTTP server. `asyncio.gather(..., return_exceptions=True)` waits for all of them and
   collects transport failures; cancelling `discover()` cancels the probes with it.
3. Each payload is matched against the models that declared its endpoint, with no further I/O. A
   model is only a candidate for a payload from an endpoint it declared.
4. A model matching on several of its endpoints is reported once, built on the first it declared.
5. Returns the full `Set[Inverter]` of every model that matched. It never auto-picks a single
   winner; ambiguity (more than one match) is surfaced to the caller, not silently resolved.
6. Failures only surface as `DiscoveryError` if *no* model matched at all.

`RealTimeAPI` in `__init__.py` wraps a single already-resolved `Inverter` with `rt_request()`,
which retries on `asyncio.TimeoutError` with exponential backoff (5, 15, 35... seconds) up to 3
attempts. Callers get that `Inverter` by calling `discover()` themselves and resolving the 0/1/N
match cases — e.g. the Home Assistant integration's config flow calls `discover()` directly and,
when more than one model matches, prompts the user to pick one and persists that choice so future
`discover()` calls can be narrowed with `inverters=[...]`.

### Schema collisions

Because discovery returns every model whose schema matches (never just a winner), an ambiguous
match — two or more models' schemas accepting the same payload — is something callers must expect
and handle, not something the library can promise away. These schemas are reverse-engineered from
observed payloads, since Solax publishes neither a protocol spec nor a model-identifying field, so
some models may be genuinely indistinguishable from a single response; tightening a schema reduces
how often that happens but can't guarantee eliminating it. Still, keep each model's `_schema` as
tight as the real firmware payload allows (exact `data` length bounds, required distinguishing
fields) — `vol.ALLOW_EXTRA` with loose length bounds is more likely to shadow a sibling model than
a genuinely irreducible collision. `tests/test_schema_ambiguity.py` checks, for every real fixture
response, that *only* the model that produced it validates against the full registry; some cases
are expected to fail permanently (see the file's `xfail` reason) rather than being a to-do list to
clear to zero.

### Adding a new inverter

1. Add `solaxng/inverters/<name>.py`, a class subclassing `Inverter` defining `_schema`,
   `response_decoder()`, and `inverter_serial_number_getter()`. Declare `endpoints` only if the
   model doesn't answer both query/body shapes; if it needs a shape no existing config describes,
   add one to `endpoints.py` rather than assembling it in the model.
2. Export it from `solaxng/inverters/__init__.py`.
3. Register it as a `solaxng.inverter` entry point in `pyproject.toml`.
4. Add a real (or sanitized) sample response and expected decoded values under `tests/samples/`,
   plus a case in `tests/fixtures.py`'s `INVERTERS_UNDER_TEST` — this feeds both
   `test_solax.py` (decoding correctness) and `test_schema_ambiguity.py` (collision safety)
   automatically.

### Key design decisions

- Plugin registry over hardcoded dispatch: `pyproject.toml` entry points are the single source of
  truth for which models exist, and let callers opt out of the full registry.
- Schema-driven identification instead of a version/model field, since Solax's protocol doesn't
  reliably expose one — making schema precision a correctness property, not just validation.
- Request shape is declared, not assembled, so the set of distinct requests is knowable without
  running anything — that's what bounds discovery's traffic by request shapes rather than models.
- Asking is separated from identifying: only the probe half touches the network, so only it needs
  staggering, timeouts and cancellation; matching is pure computation over the response.
- Single `InverterError`: `get_data()` folds network failures and schema mismatches into one
  exception type (original cause chained via `from ex`), so callers handle one type.
