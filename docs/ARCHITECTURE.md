# Architecture

This document describes how the `solaxng` library is put together: its
responsibilities, the main components, how data flows from an inverter's HTTP
endpoint to a Python object, and how new inverter models are added.

## Purpose

`solaxng` talks to the local real-time-data HTTP endpoint exposed by Solax
solar inverters (and rebadged/compatible models) and turns the raw JSON
payload into a typed, unit-aware `InverterResponse`. Because Solax does not
publish a stable protocol or a way to identify which inverter model is
answering, the library ships a schema per known model and **discovers** the
right one by trying them concurrently against the target host.

## Component map

```
src/solaxng/
├── __init__.py            RealTimeAPI + rt_request retry loop
├── discovery.py           Concurrent probing across the inverter registry
├── inverter.py            Inverter base class (schema, decoder, lifecycle)
├── inverter_http_client.py  Immutable HTTP request description + transport
├── response_parser.py     Generic envelope schema + per-sensor decoding
├── units.py                Units / Measurement value types
├── utils.py                 Small decode helpers (packers, scalers, validators)
└── inverters/                One module per supported inverter model
```

Each inverter model is a plugin registered via a `solaxng.inverter` entry point
in `pyproject.toml`, not a hardcoded list — `discovery.py` builds its registry
by reading those entry points at import time. This is what lets a caller pass
`inverters=[...]` to `discover()` and bypass the plugin lookup entirely (see
README).

## Core abstractions

### `Inverter` (`inverter.py`)

The base class every model subclasses. It owns:

- `_schema`: a `voluptuous.Schema` describing the exact shape of the JSON
  payload this model returns (field names, `data` array length bounds, the
  numeric `type` code, etc.).
- `response_decoder()`: a `Dict[str, Tuple[index_or_packer, Unit, *processors]]`
  mapping a human-readable sensor name to where its value lives in the
  `data` array and how to convert it (e.g. divide by 10, treat as signed,
  combine two 16-bit registers).
- `inverter_serial_number_getter()` / `dongle_serial_number_getter()`:
  extract identifying serials from the parsed response.

`Inverter.__init__` builds a `ResponseParser` once, wiring together the
model's schema and decoder. `build_all_variants()` produces the concrete
`Inverter` instances to probe — most models emit two variants (request
parameters in the query string vs. in the POST body) since firmware
revisions differ on which one they accept.

`get_data()` is the public entry point: it calls `make_request()` and turns
`aiohttp.ClientError` / `voluptuous.Invalid` into a single `InverterError`,
so callers only need to handle one exception type regardless of whether the
failure was network-level or a schema mismatch.

### `InverterHttpClient` (`inverter_http_client.py`)

A frozen dataclass describing *how* to talk to a single endpoint: URL,
HTTP method, password, headers, and either query-string or body data. It is
deliberately just a value object plus a `request()` method — building one
does not perform any I/O. `.replace()` supports a copy-on-write style API
(`with_headers`, `with_default_query`, `with_default_data`) and interns
identical instances via a `WeakValueDictionary` keyed on field values, so
that discovery's request-deduplication (below) can identify two `Inverter`
instances that would issue the literal same HTTP request.

### `ResponseParser` (`response_parser.py`)

Two layers of validation/decoding happen here:

1. **`GENERIC_RESPONSE_SCHEMA`** — every inverter response, regardless of
   model, must have a string `sn`, a `ver`/`version` string, a `type`
   code, and a non-empty, not-all-zero `data` array. This is checked first
   and combined (`vol.And`) with the model-specific `_schema`.
2. **Model-specific schema** — the exact `data` length range and any
   additional required top-level keys (`information`, etc.) that
   distinguish one model's payload shape from another's.

Once validation passes, `map_response()` walks the model's
`response_decoder()` to project the raw `data` array into named,
unit-converted values, then applies any post-processing functions
(`div10`, `to_signed`, `pack_u16`, …) in `utils.py`. The result is wrapped
in the `InverterResponse` namedtuple (`data`, `dongle_serial_number`,
`version`, `type`, `inverter_serial_number`).

### `units.py`

`Units` enumerates the physical units (`W`, `V`, `A`, `kWh`, `%`, …).
`Measurement` (and its `Total` / `DailyTotal` subclasses) tags a sensor with
its unit plus semantics that matter to consumers like Home Assistant:
whether the value is monotonically increasing, resets daily, or represents
stored energy. `Inverter.sensor_map()` exposes `{name: (index, Measurement)}`
derived from `response_decoder()` — this is a public contract consumed by
downstream integrations, so its shape is preserved even though the decoder
tuple format is more flexible internally (see the comment "Warning, HA
depends on this" in `inverter.py`).

## Discovery flow (`discovery.py`)

Because the same endpoint answers every request, and there is no reliable
"what model am I" field, discovery is a fan-out/fan-in over the plugin
registry:

1. Build every `(inverter_class, variant)` combination — one `Inverter`
   instance per model × query/body variant.
2. Requests that are byte-for-byte identical (same `InverterHttpClient`,
   thanks to the dataclass interning above) are deduplicated: only one
   HTTP call is made per unique request, and every `Inverter` instance
   sharing that request awaits the same `Future`. This matters because
   several models legitimately share an identical request shape and
   would otherwise triple-hit the inverter for no reason.
3. Deduplicated requests are **staggered** one second apart
   (`stagger()`) rather than fired all at once, to avoid hammering a
   small embedded HTTP server on the inverter's dongle.
4. Tasks are awaited with `asyncio.wait(..., return_when=asyncio.ALL_COMPLETED)`
   — discovery always waits for every staggered probe and returns the full
   `Set[Inverter]` of every model whose schema validated the response. It
   never auto-picks a single "winner": two schemas matching the same
   response is a correctness bug (see "Schema collisions" below), not
   something discovery should silently race and paper over.
5. Failures (network errors, schema mismatches) are collected and only
   surfaced (as a `DiscoveryError`) if *no* model matched at all.

`RealTimeAPI` (`__init__.py`) wraps a single already-resolved `Inverter`
with `rt_request()`, which retries on `asyncio.TimeoutError` with
exponential backoff (`5, 15, 35, ...` seconds) up to 3 attempts. Callers get
that `Inverter` themselves by calling `discover()` and resolving the 0/1/N
match cases explicitly — e.g. the Home Assistant integration's config flow
calls `discover()` directly and, when more than one model matches, prompts
the user to pick one and persists that choice so future `discover()` calls
can be narrowed with `inverters=[...]`.

## Schema collisions

Because discovery returns every model whose schema matches (never just a
winner), an ambiguous match — two or more models' schemas accepting the
same payload — is something callers must expect and handle, not something
the library can promise away. These schemas are reverse-engineered from
observed payloads, since Solax publishes neither a protocol spec nor a
model-identifying field, so some models may be genuinely indistinguishable
from a single response; tightening a schema reduces how often that happens
but can't guarantee eliminating it. `tests/test_schema_ambiguity.py` guards
against the fixable kind: for every real fixture response, it checks that
*only* the model that produced that fixture validates it against the full
registry, and exposes a permissiveness ranking (`python -m
tests.test_schema_ambiguity`) to help identify which schema needs to be
tightened when a collision is found. Keeping each model's `_schema` as
tight as the real firmware payload allows (exact `data` length bounds,
required distinguishing fields) is what keeps this test meaningful — a
schema that uses `vol.ALLOW_EXTRA` and loose length bounds is more likely
to shadow a sibling model than a genuinely irreducible collision. Some
fixture cases are expected to fail this check permanently rather than be a
to-do list to clear to zero — see the `xfail` reason in the test file.

## Extension point: adding a new inverter

1. Add `solaxng/inverters/<name>.py` with a class subclassing `Inverter`
   that defines `_schema`, `response_decoder()`, and
   `inverter_serial_number_getter()`. Override `build_all_variants()` only
   if the model doesn't support both query/body variants.
2. Export it from `solaxng/inverters/__init__.py`.
3. Register it as a `solaxng.inverter` entry point in `pyproject.toml`.
4. Add a real (or sanitized) sample response and its expected decoded
   values under `tests/samples/`, and a case in `tests/fixtures.py`'s
   `INVERTERS_UNDER_TEST` — this is what feeds both `test_solax.py`
   (decoding correctness) and `test_schema_ambiguity.py` (collision
   safety) automatically.

## Key design decisions

- **Plugin registry over a hardcoded dispatch table.** Entry points let a
  caller opt out of the full registry (`discover(..., inverters=[...])`)
  without forking the library, and keep `pyproject.toml` as the single source
  of truth for "which models exist."
- **Schema-driven identification instead of a version/model field.**
  Solax's protocol doesn't reliably expose a model identifier, so
  "does this model's schema accept this payload" is the only available
  discriminator. This makes schema precision (previous section) a
  correctness property, not just data validation.
- **Immutable, interned `InverterHttpClient`.** Modeling the HTTP request
  as a value object (rather than performing I/O eagerly per `Inverter`)
  is what makes request deduplication during discovery possible.
- **Single `InverterError`.** Consumers of `get_data()` don't need to
  distinguish network failures from malformed/unexpected payloads at the
  call site; both are folded into one exception type with the original
  cause chained via `from ex`.
