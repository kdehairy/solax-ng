# utils

Operator tools for working on this library. Nothing here is packaged or published — the wheel and
sdist only contain `src/solaxng`.

## `discover_inverter.py`

Points the library at a real inverter and shows what came back:

1. asks for the host/IP (a full `http://10.0.0.1:80/` URL works too), port and password,
2. runs `solaxng.discover()`,
3. lists every model whose schema accepted the response,
4. fetches a fresh payload with the model you pick and prints it labeled through that model's
   sensor map.

```sh
make discover                                      # prompts for everything
uv run python utils/discover_inverter.py --host 10.0.0.1 --port 80
uv run python utils/discover_inverter.py --host 10.0.0.1 --raw
uv run python utils/discover_inverter.py --host 10.0.0.1 --save response.json
```

Passing `--host` skips the prompts, so the port defaults to 80 and the password to empty.

`--raw` additionally dumps the raw `data` array with each index annotated with the sensor reading
it, or `(unmapped)` — useful when reverse-engineering a model or checking that a schema isn't
leaving values on the table. `--save` writes the response exactly as received, which is the
starting point for a `tests/samples/` fixture. `--verbose` shows the library's per-endpoint probe
logging.

More than one candidate is a normal outcome, not a failure: the schemas are reverse-engineered from
observed payloads and two models can be indistinguishable from a single response, so `discover()`
reports every match rather than guessing one.
