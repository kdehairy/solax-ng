# Solax local API docs

Reverse-engineered documentation for local API on inverters built by Solax Power.

Manufacturer didn't want to provide documentation (and it would be mess, I can see why), but we (users) want to have
cloud-free access to real-time data using existing APIs (for instance, to use in Home Assistant) and thus need a way to
interpret the data anyway.

The route I took was to extract information from official Android application (originally version 0.4.5), which turns
out is built with Apache Cordova and contains all the necessary logic in minified JavaScript.

This approach allows us to not guess what values mean what and to support all inverters that official app supports.

The information contained in this repository is the result of un-tangling that minified JavaScript and transforming into
human-readable pseudo-code.

**Update:** `Data2.txt`, `Information.txt` and the inverter type table below were re-derived from SolaXCloud
`7.7.1` (`SolaXCloud_7.7.1_APKPure.apk`). The local-connection screens (and the `getRealTimeData`/`Data2.txt` decoding
logic) still live in the same Cordova/Vue2 webview bundle as before, just with a lot more inverter types and a few
extra fields added over time; anything documented for a given `inverterType` in earlier versions of this repo that is
still present in 7.7.1 was double-checked against the app and kept as-is (or corrected where it had actually changed),
new `inverterType` codes were added, and offsets that changed were updated.

In order to get the data you'll need to make request to your inverter:
```bash
curl -d "?optType=ReadRealTimeData&pwd=PASSWORD" -X POST http://IP_ADDRESS
```

* `PASSWORD` is the password used for local access to the data in the app, it defaults to the serial number of the Pocket
Wi-Fi (most Pocket Lan dongles do not expose local API at all).
* `IP_ADDRESS` is the IP address of the inverter given by your router, something like `192.168.1.105`

Typical response from API looks something like this (X1-Hybrid G4):
```json
{
  "sn": "SV********",
  "ver": "3.003.02",
  "type": 15,
  "Data": [ A LOT OF NUMBERS HERE ],
  "Information": [ 5.000, 15, "H4************", 8, 1.30, 0.00, 1.28, 1.04, 0.00, 1]
}
```

When there's an active fault, the response also gets a top-level `Error` object (see `Errors.txt`):
```json
{
  "Error": {
    "ErrorCode": "16,27",
    "ErrorCodeNew": "101_5,205_1"
  }
}
```

# Known inverter types

Inverter type is both contained in `type` field of the response and, apparently, in `Information` field as well.
At least this is true for most inverters.

These are the known inverter types based on https://github.com/squishykid/solax, please add yours in PR:
* `3`
  * Solax Power X1-Hybrid G1, G2, G3
* `5`
  * Solax Power X3-Hybrid G1, G2, G3
  * PEIMAR NOCTIS PSI-X3
* `8`
  * Solax Power X1-Smart
* `14`
  * Solax Power X3-Hybrid G4
  * Qcells Q.VOLT HYB-G3-3P
  * PEIMAR NOCTIS PSI-X3S
* `15`
  * Solax Power X1-Hybrid G4
  * Qcells Q.VOLT HYB-G3-1P
  * PEIMAR NOCTIS PSI-X1

Here is how they are named in the application's source code (re-derived from SolaXCloud 7.7.1; entries
below the `x1hybridlv` line are new compared to earlier versions of this document):

| Name             | inverterType |
|------------------|--------------|
| x1hybridg3       | 3            |
| x1boostairmini   | 4            |
| x3hybridg1       | 5            |
| x320k30k         | 6            |
| x3mic            | 7            |
| x1boostpro       | 8            |
| x1ac             | 9            |
| a1hybrid         | 10,11,12     |
| j1ess            | 13           |
| x3hybridg4       | 14           |
| x1hybridg4       | 15           |
| x3micprog2       | 16           |
| x1hybridsplitg4  | 17           |
| x1boostminig4    | 18,22,26     |
| a1hybridg2       | 19,20,21     |
| x1hybridg5       | 23           |
| x3hybridg5       | 24,39,40     |
| x3hybrid1530kw   | 25,43        |
| x3alieo          | 31           |
| x3hybridg4plus   | 32           |
| x3hugelv         | 33           |
| x1vast10k        | 34           |
| x3iesp           | 35           |
| j3ult            | 36,37        |
| j1ess2           | 38           |
| x1iesa           | 41           |
| x1minig4plus     | 44           |
| x1renolv         | 46           |
| a1hybridg3       | 47           |
| x1vibeog         | 64           |
| x1spt10k12k      | 66           |
| x1hybridlvg2     | 67           |
| aegis            | 69           |
| x3big            | 100,101      |
| x1hybridlv       | 102          |
| x1litelv         | 103          |
| x3grandhv        | 104          |
| x3forthplus      | 105          |
| x3micg3          | 108,109      |
| forthg3          | 111          |

`inverterType` 26 shares its settings screen with 18/22 (`x1boostminig4`) but decodes its `Data` array with
different offsets in `Data2.txt` - it's most likely a hardware/firmware variant. `inverterType` 43 shares its
`Data2.txt` decoding with 25 (`x3hybrid1530kw`) but its screen wasn't found named separately in the app, so it's
probably an internal variant of the same product line.

The app also references `inverterType` 27, 28 and 29 for balcony/micro-inverter installations. Those are routed
to a completely different settings/monitoring flow (`category = 2`, micro-inverter setting UI) that doesn't use
the `getRealTimeData`/`Data2.txt` decoding described here, so they are **not** covered by `Data2.txt` or
`Information.txt` in this repository.

## Contents of this repository

There are a few key files listed below that contain mapping and pseudocode explaining usage or parsing algorithm.
Only information in the source code of the app was used to derive mappings, there might be other meaningful fields that
are not present in the app.

There might be bugs, for instance I didn't include main battery serial number parsing because it returns garbage on my
inverter and I can't guarantee that it makes sense on any model (application doesn't show it despite containing code
that parses it).

There are no promises whatsoever, so use this at your own risk.

Application also, naturally, contains code to control the inverter, but due to risks involved with changing those
parameters, they are not (yet?) documented here. It would have been nice to automate things with Home Assistant though.

### Information.txt

This file helps to get some high-level information about inverter and understand how to interpret the rest of the data
based on `Information` field of the response.

By knowing which inverter type it is, you can look into `Data1.txt` or `Data2.txt` for further details.

It also documents `RunMode` value tables per inverterType, and a set of derived flags the official app computes on
top of `Data`/`Information` per inverterType (which types never have a battery or PV input, when generator/third-party
meter fields are actually meaningful, and the numeric `RunMode` thresholds used to detect EPS/backup mode - which
isn't simply `RunMode == 7` for most types).

### Data1.txt

Seems to be older version of the API for some earlier inverter models, has generic mapping for all matching models and
should be assumed to have many of the fields as optional since I was not able to deduce clear mapping between different
models.

### Data2.txt

Seems to be modern version of the API, has clear mapping between inverter type and decoding rules.
The same parameter doesn't always occupy the same offset in `Data` field, hence more boilerplate would be necessary to
parse it.

### DataEvCharger.txt

Serial number can apparently be in either `sn` or `SN` fields of the response.

Serial numbers starting with "SC" and "SQ" appear to be related to EV chargers.
Serial numbers starting with "SD" appear to be related to Adapter Box.

`DataEvCharger.txt` contains mapping to decode real-time data from such EV chargers.

### Errors.txt

Per-inverterType fault/alarm code -> message tables. The raw codes come from the same `ReadRealTimeData` response
documented above, in a top-level `Error` object (`Error.ErrorCode`/`Error.ErrorCodeNew`, sibling to `Data`/
`Information`) rather than from any offset inside the `Data` array itself - see the top of `Errors.txt` for the
exact shape and which inverterType codes use the legacy vs. the newer composite code format.

## License

Public Domain

## Due Credit
This is a _updated_ copy of the original work done [here](https://github.com/nazar-pc/solax-local-api-docs)
