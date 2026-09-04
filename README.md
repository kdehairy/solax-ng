# Solax

[![Build Status](https://github.com/kdehairy/solax-ng/workflows/tests/badge.svg)](https://github.com/kdehairy/solax-ng/actions)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/solax-ng.svg)](https://pypi.org/project/solax-ng)

Read energy usage data from the real-time API on Solax solar inverters.

* Real time power, current and voltage
* Grid power information
* Battery level
* Temperature and inverter health
* Daily/Total energy summaries

## Usage

`pip install solax-ng`

Then from within your project:

```
import solaxng
import asyncio

async def work():
    inverters = await solaxng.discover('10.0.0.1', 80)
    if len(inverters) != 1:
        # This quickstart doesn't handle ambiguous matches - see below.
        raise RuntimeError(f"Expected exactly one inverter to match, got: {inverters}")
    api = solaxng.RealTimeAPI(next(iter(inverters)))
    return await api.get_data()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
data = loop.run_until_complete(work())
print(data)
```

`discover()` tries all the inverter classes concurrently and returns the full set of every one
whose schema matched your inverter's response — usually exactly one, but not always. Solax doesn't
publish a protocol spec or a model-identifying field, so these schemas are reverse-engineered from
observed payloads, and two models can genuinely be indistinguishable from a single response.
`discover()` never guesses on your behalf — it just hands back everything that matched, and it's up
to the caller to decide what that means. You can see the list of inverter implementation classes in
the entry points configured in [pyproject.toml](pyproject.toml).

If the set is empty, `discover()` raises `DiscoveryError`. If it has more than one entry, a real
application should expect that and handle it deliberately — e.g. ask the user to pick a model once
and remember that choice, which is what the Home Assistant integration's config flow does — rather
than treat it as a one-off error like the snippet above does. Narrowing the search to a specific
class up front, as shown below, is both how you'd apply that remembered choice and the pattern to
use if you already know your inverter model and want to skip the concurrent probing.

```
from importlib.metadata import entry_points
import solaxng
import asyncio

INVERTERS_ENTRY_POINTS = {
   ep.name: ep.load() for ep in entry_points(group="solaxng.inverter")
}

async def work():
    inverters = await solaxng.discover("10.0.0.1", 80, "xxxxx", inverters=[INVERTERS_ENTRY_POINTS.get("x1_hybrid_gen4")])
    inverter = next(iter(inverters))
    return await inverter.get_data()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
data = loop.run_until_complete(work())
print(data)
```

## Confirmed Supported Inverters

These inverters have been tested and confirmed to be working. If your inverter is not listed below, this library may still work- please create an issue so we can add your inverter to the list 😊.

* SK-TL5000E
* X1 Hybrid Gen4

You can get the list of supported inverters by looking up the `solaxng.inverter` entry points:

```
for ep in entry_points(group="solaxng.inverter"):
    print(ep)
```