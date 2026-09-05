# Solax

[![Build Status](https://github.com/kdehairy/solax-ng/workflows/tests/badge.svg)](https://github.com/kdehairy/solax-ng/actions)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/solax-ng.svg)](https://pypi.org/project/solax-ng)

Read energy usage data from the real-time API on Solax solar inverters.

* Real time power, current and voltage
* Grid power information
* Battery level
* Temperature and inverter health
* Daily/Total energy summaries

## Origin
This is a hard fork of [original repo](https://github.com/squishykid/solax). The original project
seems to be unmaintained for a while.

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

`discover()` asks your inverter once per distinct request shape the known models use, then returns
the full set of every model whose schema matched a response — at most one entry per model, usually
exactly one entry in total, but not always. Solax doesn't publish a protocol spec or a 
model-identifying field, so these schemas are reverse-engineered from observed payloads, and two 
models can genuinely be indistinguishable from a single response. `discover()` never guesses on 
your behalf — it just hands back everything that matched, and it's up to the caller to decide what 
that means. You can see the list of inverter implementation classes in the entry points configured 
in [pyproject.toml](pyproject.toml).

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

* QVOLTHYBG33P (QVOLTHYBG33P)
* X1
* X1 Boost
* X1 G4 Series
* X1 Hybrid Gen4
* X1 Mini
* X1 Mini v34
* X1 Smart
* X1 Lite LV
* X3
* X3 Hybrid G4
* X3 Ultra
* X3 Mic Pro G2
* X3 v34
* X Hybrid
* X3 EVC

You can get the list of supported inverters by looking up the `solaxng.inverter` entry points:

```
for ep in entry_points(group="solaxng.inverter"):
    print(ep)
```
