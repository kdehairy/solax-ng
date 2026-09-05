"""
Evidence gathering for an inverter no registered model recognises.

``discover()`` throws the payloads away when nothing matches, so this module
probes the endpoints again, keeps what came back, works out why every model
rejected it, and writes the findings as a Markdown document. The sensor
mapping table is left blank -- nobody can derive it from a payload alone.

Part of the operator tooling, not of the published library.
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from voluptuous import Invalid, MultipleInvalid
from voluptuous.humanize import humanize_error

from solaxng.discovery import REGISTRY, STAGGER_SECONDS
from solaxng.endpoints import EndpointConfig
from solaxng.inverter_http_client import InverterHttpClient
from solaxng.response_parser import GENERIC_RESPONSE_SCHEMA

if sys.version_info >= (3, 10):
    from importlib.metadata import PackageNotFoundError, version
else:
    from importlib_metadata import PackageNotFoundError, version

DETAIL_LIMIT = 120
PREVIEW_LIMIT = 500


class Probe(NamedTuple):
    """One request shape, and whatever came back from it."""

    endpoint: EndpointConfig
    http_client: InverterHttpClient
    payload: Optional[bytes]
    error: Optional[BaseException]


class Observation(NamedTuple):
    """One distinct payload, and every endpoint that returned it."""

    payload: bytes
    probes: List[Probe]
    document: Optional[Dict[str, Any]]
    parse_error: Optional[str]


class Verdict(NamedTuple):
    """What one registered model made of a payload."""

    model: str
    accepted: bool
    detail: str


def probe_endpoints() -> Tuple[EndpointConfig, ...]:
    """Every request shape any registered model declares, in declaration order."""
    return tuple(dict.fromkeys(ep for cls in REGISTRY for ep in cls.endpoints))


async def _probe(http_client: InverterHttpClient, delay: float) -> Any:
    await asyncio.sleep(delay)
    return await http_client.request()


async def collect(host: str, port: int, pwd: str) -> List[Probe]:
    """
    Ask every known request shape once, staggered the way discovery does it.

    Only reached once discovery has already failed, so the second round of
    requests costs nothing on the path where the inverter is recognised.
    """
    configs = probe_endpoints()
    clients = [config.build(host, port, pwd) for config in configs]
    results = await asyncio.gather(
        *(
            _probe(client, position * STAGGER_SECONDS)
            for position, client in enumerate(clients)
        ),
        return_exceptions=True,
    )

    probes = []
    for config, client, result in zip(configs, clients, results):
        if isinstance(result, BaseException):
            probes.append(Probe(config, client, None, result))
        else:
            probes.append(Probe(config, client, bytes(result), None))
    return probes


def normalize(payload: bytes) -> Dict[str, Any]:
    """
    Parse a payload exactly the way ``ResponseParser.handle_response`` does.

    Same decode, same doubled comma repair, same key lowercasing, so the keys
    and indexes in this document are the ones a schema will be judged against.
    """
    text = payload.decode("utf-8").replace(",,", ",0.0,").replace(",,", ",0.0,")
    return {str(key).lower(): value for key, value in json.loads(text).items()}


def observations(probes: Sequence[Probe]) -> List[Observation]:
    """Group the answers by payload, so identical replies are described once."""
    grouped: Dict[bytes, List[Probe]] = {}
    for probe in probes:
        if probe.payload is not None:
            grouped.setdefault(probe.payload, []).append(probe)

    result = []
    for payload, members in grouped.items():
        document: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None
        try:
            document = normalize(payload)
        except Exception as ex:  # pylint: disable=broad-except
            parse_error = f"{type(ex).__name__}: {ex}"
        result.append(Observation(payload, members, document, parse_error))
    return result


def _one_line(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > DETAIL_LIMIT:
        collapsed = collapsed[: DETAIL_LIMIT - 1] + "…"
    return collapsed.replace("|", "\\|")


def envelope_error(document: Dict[str, Any]) -> Optional[str]:
    """Why the generic envelope rejected the payload, if it did."""
    try:
        GENERIC_RESPONSE_SCHEMA(dict(document))
    except (Invalid, MultipleInvalid) as ex:
        return _one_line(humanize_error(document, ex))
    return None


def verdicts(document: Dict[str, Any]) -> List[Verdict]:
    """What every registered model's own schema made of the payload."""
    result = []
    for cls in REGISTRY:
        try:
            cls.schema()(dict(document))
        except (Invalid, MultipleInvalid) as ex:
            result.append(
                Verdict(cls.__name__, False, _one_line(humanize_error(document, ex)))
            )
        except Exception as ex:  # pylint: disable=broad-except
            result.append(
                Verdict(cls.__name__, False, _one_line(f"{type(ex).__name__}: {ex}"))
            )
        else:
            result.append(Verdict(cls.__name__, True, ""))
    return result


def library_version() -> str:
    try:
        return version("solax-ng")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"


def _data(document: Optional[Dict[str, Any]]) -> List[Any]:
    values = (document or {}).get("data")
    return values if isinstance(values, list) else []


def _information(document: Optional[Dict[str, Any]]) -> Optional[List[Any]]:
    values = (document or {}).get("information")
    return values if isinstance(values, list) else None


def _version_key(document: Dict[str, Any]) -> str:
    return "ver" if "ver" in document else "version"


def _endpoint_line(probe: Probe) -> str:
    config = probe.endpoint
    bits = []
    if config.send_params:
        bits.append("params in " + ("query" if config.params_in_query else "body"))
    if config.use_pwd:
        bits.append("pwd sent")
    if config.headers:
        bits.append(f"headers={dict(config.headers)}")
    suffix = f" ({', '.join(bits)})" if bits else ""
    return (
        f"- **{config.name}**: `{config.method.name} {probe.http_client.url}`{suffix}"
    )


def _preview(payload: bytes) -> str:
    text = payload[:PREVIEW_LIMIT].decode("utf-8", errors="replace")
    return text + ("…" if len(payload) > PREVIEW_LIMIT else "")


def _envelope_section(document: Dict[str, Any]) -> List[str]:
    data = _data(document)
    information = _information(document)
    known = {"sn", "ver", "version", "type", "data", "information"}
    extra = sorted(key for key in document if key not in known)

    rows = [
        ("sn", json.dumps(document.get("sn"))),
        (_version_key(document), json.dumps(document.get(_version_key(document)))),
        (
            "type",
            f"{json.dumps(document.get('type'))} "
            f"({type(document.get('type')).__name__})",
        ),
        ("len(data)", str(len(data))),
        (
            "len(information)",
            str(len(information)) if information is not None else "no such key",
        ),
        ("other top-level keys", ", ".join(extra) if extra else "none"),
    ]
    return [f"- `{label}`: `{value}`" for label, value in rows]


def _rejection_section(document: Dict[str, Any]) -> List[str]:
    lines = ["### Rejected by", ""]

    envelope = envelope_error(document)
    if envelope is not None:
        lines += [
            f"- generic envelope check (`GENERIC_RESPONSE_SCHEMA`): {envelope}",
            "",
        ]
        return lines

    results = verdicts(document)
    lines += ["| model | verdict | reason |", "| --- | --- | --- |"]
    for verdict in results:
        mark = "accepts" if verdict.accepted else "rejects"
        lines.append(f"| `{verdict.model}` | {mark} | {verdict.detail} |")
    lines.append("")

    accepting = [verdict.model for verdict in results if verdict.accepted]
    if accepting:
        lines += [
            f"Note: {', '.join(accepting)} actually accept this payload here, so "
            "discovery's mismatch was likely a transport failure, not a missing "
            "model — re-run the tool before writing new code.",
            "",
        ]
    return lines


def _mapping_section(document: Dict[str, Any]) -> List[str]:
    data = _data(document)
    lines = [
        "### Data mapping (fill in)",
        "",
        "One row per `data` index; the other three columns are for a human to "
        "fill in by reading the matching value off the inverter's display/app.",
        "",
        "| index | raw value | sensor name | unit | transform |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {index} | {json.dumps(value)} |  |  |  |"
        for index, value in enumerate(data)
    ]
    lines.append("")
    return lines


def render(host: str, port: int, probes: Sequence[Probe]) -> str:
    """Build the whole document from one round of probes."""
    answered = observations(probes)
    silent = [probe for probe in probes if probe.payload is None]

    lines = [
        "# Unsupported Solax inverter",
        "",
        f"`utils/discover_inverter.py`, {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, "
        f"`{host}:{port}`, solax-ng {library_version()}, {len(REGISTRY)} models "
        "checked, none matched.",
        "",
        "> Serial numbers below are real. Replace them with `XXXXXXX` before "
        "committing any of this as a test fixture.",
        "",
    ]

    for position, observation in enumerate(answered, start=1):
        heading = "## Response" if len(answered) == 1 else f"## Response {position}"
        lines += [heading, "", "Answered on:", ""]
        lines += [_endpoint_line(probe) for probe in observation.probes]
        lines.append("")

        if observation.document is None:
            lines += [
                f"Payload is not JSON ({observation.parse_error}); first bytes:",
                "",
                "```",
                _preview(observation.payload),
                "```",
                "",
            ]
            continue

        lines += ["### Envelope", ""]
        lines += _envelope_section(observation.document)
        lines += [
            "",
            "### Full response",
            "",
            "```json",
            json.dumps(observation.document, indent=2),
            "```",
            "",
        ]
        lines += _rejection_section(observation.document)
        lines += _mapping_section(observation.document)

    if silent:
        lines += ["## Endpoints that did not answer", ""]
        lines += [
            f"- **{probe.endpoint.name}**: {type(probe.error).__name__}: {probe.error}"
            for probe in silent
        ]
        lines.append("")

    lines += [
        "## Adding this model",
        "",
        "1. Add `src/solaxng/inverters/<name>.py` subclassing `Inverter`: pin "
        "`_schema`'s `type` and the exact `data`/`information` lengths to what's "
        "shown above, declare `endpoints` if it isn't the default "
        "`(POST_QUERY, POST_BODY)`, fill in `response_decoder()` from the "
        "mapping table, and implement `inverter_serial_number_getter`.",
        "2. Export it from `src/solaxng/inverters/__init__.py` and register it as "
        "a `solaxng.inverter` entry point in `pyproject.toml`.",
        "3. Add a sample response and its expected decoded values under "
        "`tests/samples/`, and a matching case in `tests/fixtures.py`'s "
        "`INVERTERS_UNDER_TEST`.",
        "4. Run `make verify` and "
        "`uv run python -m tests.test_schema_ambiguity`; re-run this tool and "
        "confirm the new model is the sole candidate.",
        "",
        'See `AGENTS.md`\'s "Adding a new inverter" for the full mechanics, and '
        "`tests/test_schema_strictness.py` / `tests/test_schema_ambiguity.py` for "
        "what the new schema has to satisfy.",
    ]
    return "\n".join(lines)
