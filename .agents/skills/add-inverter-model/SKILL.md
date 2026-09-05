---
id: add-inverter-model
name: Add Inverter Model
description: "Adds solaxng support for a Solax inverter model that discover() doesn't recognize yet: runs the discovery tool to gather evidence, interviews the user to fill in the sensor mapping, drafts an implementation plan, and, once the user approves, implements and verifies the new model."
enabled: true
---

# Add Inverter Model

`solaxng` identifies inverters by matching a response against each registered
model's schema; there is no protocol-level model-ID field. When none of the
registered schemas accept a response, the inverter is simply unsupported yet.
This skill turns that situation into a working, tested addition to the
library, in five steps: gather evidence, interview the user for what the
tool cannot know on its own, draft a plan, get approval, implement and
verify.

Use it whenever the user's inverter isn't recognized, or they otherwise ask
to add support for a new Solax (or rebadged/compatible) inverter model.

This skill assumes only the ability to run shell commands in the repository,
read and write files in it, and hold a conversation with the user for
approval. It does not depend on any particular AI product or tool-calling
convention.

## Step 1 — Gather evidence

Ask the user for the inverter's host or IP address, port (default 80), and
password if it has one. Pass these explicitly with `--host`/`--port`/`--pwd`
rather than relying on the tool's interactive prompts, since not every
environment running this skill can answer an interactive stdin prompt.

From the repository root, run:

```sh
uv run python -m utils.discover_inverter --host <host> --port <port> --report <path>.md
```

(`-m utils.discover_inverter` must be run from the repository root — that
package is not installed, only present in the checkout.)

Interpret the exit code:

- **0** — a model already matched. The inverter is already supported; tell
  the user and stop.
- **3** — no model matched, and a report was written to `<path>.md`.
  Continue to Step 2.
- **1** — the inverter could not be reached on any known request shape. Help
  the user fix connectivity (host/port/network) and retry before continuing.
- **2** — the report or `--save` path already exists. Pick a different path,
  or reuse an existing report if the user already has one from this same
  inverter.

If the user already has a report from a previous run, use it instead of
probing the inverter again.

Read the report. It documents, as observed fact: which request shapes the
inverter answered, the full normalized response, why every registered
model's schema rejected it, and a data-mapping table with the raw value at
each index and blank columns for sensor name, unit and transform.

## Step 2 — Interview the user for the sensor mapping

The raw values in the report are meaningless without a human who can read
the inverter's own display, app, or monitoring portal at (or near) the
moment the report was captured. Go through the mapping table and, for each
index that isn't obviously padding/reserved:

- Show the raw value and ask what real-world reading it corresponds to.
- If the value's magnitude suggests a plausible unit and scale (e.g. `2396`
  as a voltage reading of `239.6 V` once divided by 10), propose it and ask
  the user to confirm or correct it — never assert a mapping the user hasn't
  confirmed.
- Watch for a value that only makes sense combined with its neighbor (e.g. a
  running total that would otherwise overflow a 16-bit register) — that's a
  packed value spanning two indices.
- Record, per identified sensor: name, unit, and transform, using only the
  vocabulary the library already has:
  - units — `src/solaxng/units.py`: `Units.W`, `Units.KWH`, `Units.A`,
    `Units.V`, `Units.C`, `Units.HZ`, `Units.PERCENT`, `Units.NONE`; wrap a
    running total as `Total(Units.KWH)`, a value that resets at midnight as
    `DailyTotal(Units.KWH)`.
  - transforms — `src/solaxng/utils.py`: `div10`, `div100`, `to_signed`,
    `to_signed32`, `twoway_div10`, `twoway_div100`, and `pack_u16(i, j)` for
    two registers packed least-significant-first.
- It is fine to leave an index unidentified if the user doesn't know — note
  it as unmapped rather than inventing a name for it.

Also ask:

- Which index of `information` (if the report shows one) holds the inverter
  serial number.
- The model's marketing name and, if visible in the report's envelope
  (`ver`/`version`), the firmware/dongle version — these name the new class
  and module.

## Step 3 — Draft an implementation plan

Before changing anything, write out a concrete plan covering:

1. **`src/solaxng/inverters/<name>.py`** — a new `Inverter` subclass: `_schema`
   with `type` pinned to the exact literal observed and `data`/`information`
   validated with exact-length constraints (`min == max`) from the report;
   `endpoints` declared only if it differs from the default
   `(POST_QUERY, POST_BODY)`; `response_decoder()` filled in from the
   confirmed mapping; `inverter_serial_number_getter` using the confirmed
   index.
2. **`src/solaxng/inverters/__init__.py`** — import the new class and add it
   to `__all__`.
3. **`pyproject.toml`** — a new line under
   `[project.entry-points."solaxng.inverter"]` registering the class.
4. **Test fixture** — the response as a constant in `tests/samples/responses.py`
   (serial numbers replaced with `XXXXXXX`), the expected decoded values in
   `tests/samples/expected_values.py`, and a matching `InverterUnderTest`
   entry in `tests/fixtures.py`'s `INVERTERS_UNDER_TEST` (`uri`, `method`,
   `query_string`, `headers`, `data` taken from whichever endpoint answered
   in the report).
5. **Verification** — `make verify`; `uv run python -m
   tests.test_schema_ambiguity`; then, if the inverter is still reachable,
   re-running `utils/discover_inverter.py` against it and confirming the new
   model is now the sole candidate.

Present this plan to the user and get their explicit approval before
changing anything in the repository. If the environment running this skill
has its own mechanism for proposing a plan and asking for confirmation, use
it; otherwise, simply state the plan and wait for the user to say to
proceed.

## Step 4 — Implement (only after approval)

Make exactly the changes from the approved plan. While doing so:

- Match the schema conventions already used in `src/solaxng/inverters/`: pin
  `type` to the literal/pattern actually observed (never a bare `int`/`str`
  check), and use `vol.Any(vol.Length(a), vol.Length(b), ...)` rather than an
  open length range if more than one exact length is genuinely observed —
  see `tests/test_schema_strictness.py` for the structural rules this is
  checked against.
- Keep `Inverter.sensor_map()`'s derived shape intact; only extend
  `response_decoder()`, don't restructure how it's read.
- Add the fixture entry so the new model is automatically exercised by both
  `tests/test_solax.py` (decoding correctness) and
  `tests/test_schema_ambiguity.py` (collision safety) — see `CLAUDE.md`'s
  "Adding a new inverter" section for the full mechanics this mirrors.

## Step 5 — Verify

- Run `make verify` (formatting, isort, mypy, flake8, pylint, and pytest with
  a 100%-coverage gate) and fix anything it flags before calling the task
  done.
- Run `uv run python -m tests.test_schema_ambiguity`. If it reports a
  collision with an existing model, that is not automatically a bug —
  tighten whichever schema is more permissive first (the module ranks
  schemas by permissiveness when run standalone), and only record the pair
  as a documented, deliberate collision if the two models are genuinely
  indistinguishable from a single response.
- If the real inverter is still reachable, re-run
  `uv run python -m utils.discover_inverter --host <host> --raw` and confirm
  it now reports exactly the new model, with every sensor value matching
  what the inverter's own display shows.

## Notes

- Never invent a sensor name, unit, or transform without the user's
  confirmation. The purpose of this workflow is to replace guessing with a
  verified mapping — an unconfirmed guess baked into `response_decoder()` is
  worse than an honestly unmapped index.
- An ambiguous match between two schemas can be inherent, not a defect: some
  Solax-compatible models are genuinely indistinguishable from a single
  payload. See the module docstring of `tests/test_schema_ambiguity.py`.
