"""
Interactive discovery and inspection tool for a local Solax inverter.

Point it at an inverter, see which model schemas claim the response, pick one,
and read back the payload decoded through that model's sensor map.

This is an operator tool, not part of the published library.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import aiohttp

from solaxng import discover
from solaxng.discovery import DiscoveryError
from solaxng.inverter import Inverter, InverterError
from solaxng.response_parser import InverterResponse

if sys.version_info >= (3, 10):
    from importlib.metadata import entry_points
else:
    from importlib_metadata import entry_points

DEFAULT_PORT = 80


def entry_point_names() -> Dict[type, str]:
    """Map an inverter class back to the entry point name that registers it."""
    names: Dict[type, str] = {}
    for entry_point in entry_points(group="solaxng.inverter"):
        names.setdefault(entry_point.load(), entry_point.name)
    return names


def split_target(raw: str) -> Tuple[str, Optional[int]]:
    """
    Split a host, an IP or a full URL into a host and an optional port.

    ``urlparse`` only recognises a netloc after a ``//``, so a bare
    ``10.0.0.1:80`` gets one prepended before parsing.
    """
    text = raw.strip()
    if "//" not in text:
        text = "//" + text
    parsed = urlparse(text)
    return parsed.hostname or "", parsed.port


def ask(question: str) -> str:
    try:
        return input(question).strip()
    except EOFError:
        print()
        raise KeyboardInterrupt from None


def ask_port() -> int:
    while True:
        answer = ask(f"Port [{DEFAULT_PORT}]: ")
        if not answer:
            return DEFAULT_PORT
        try:
            return int(answer)
        except ValueError:
            print(f"'{answer}' is not a port number.")


def resolve_target(args: argparse.Namespace) -> Tuple[str, int, str]:
    """
    Work out where to look.

    Passing --host means the caller knows what they want, so the remaining
    values fall back to their defaults instead of prompting.
    """
    if args.host is not None:
        host, url_port = split_target(args.host)
        port = args.port or url_port or DEFAULT_PORT
        return host, port, args.pwd or ""

    host, url_port = split_target(ask("Inverter host, IP or URL: "))
    if not host:
        print("No host given.", file=sys.stderr)
        sys.exit(2)

    port = args.port or url_port or ask_port()
    pwd = args.pwd if args.pwd is not None else ask("Password (blank if none): ")
    return host, port, pwd


def endpoint_name(inverter: Inverter, host: str, port: int, pwd: str) -> str:
    """Name the request shape this inverter was matched on."""
    for endpoint in type(inverter).endpoints:
        if endpoint.build(host, port, pwd) == inverter.http_client:
            return endpoint.name
    return "unknown"


def describe(inverter: Inverter, host: str, port: int, pwd: str) -> str:
    names = entry_point_names()
    cls = type(inverter)
    entry_point = names.get(cls, "not registered")
    return (
        f"{cls.__name__} "
        f"(entry point: {entry_point}, endpoint: {endpoint_name(inverter, host, port, pwd)})"
    )


def choose(candidates: Sequence[Inverter], host: str, port: int, pwd: str) -> Inverter:
    """Show what matched and let the user pick one."""
    print(f"\n{len(candidates)} model(s) matched:")
    for position, inverter in enumerate(candidates, start=1):
        print(f"  {position}) {describe(inverter, host, port, pwd)}")

    if len(candidates) == 1:
        print("\nOnly one match, selecting it.")
        return candidates[0]

    count_word = "Two" if len(candidates) == 2 else str(len(candidates))
    print(f"\n{count_word} candidate models. Which one is your inverter?")

    while True:
        answer = ask(f"Select [1-{len(candidates)}] (q to quit): ")
        if answer.lower() in ("q", "quit"):
            raise KeyboardInterrupt
        try:
            choice = int(answer)
        except ValueError:
            choice = 0
        if 1 <= choice <= len(candidates):
            return candidates[choice - 1]
        print(f"Pick a number between 1 and {len(candidates)}.")


def format_value(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        text = f"{value:.3f}".rstrip("0")
        return text + "0" if text.endswith(".") else text
    return str(value)


def print_header(
    inverter: Inverter, response: InverterResponse, host: str, port: int, pwd: str
) -> None:
    fields = [
        ("Model", describe(inverter, host, port, pwd)),
        ("URL", str(inverter.http_client)),
        ("Dongle serial", response.dongle_serial_number),
        ("Inverter serial", response.inverter_serial_number),
        ("Version", response.version),
        ("Type", response.type),
    ]
    width = max(len(label) for label, _ in fields)
    print()
    for label, value in fields:
        print(f"  {label:<{width}}  {value}")


def print_sensors(inverter: Inverter, response: InverterResponse) -> None:
    sensor_map = type(inverter).sensor_map()
    rows: List[Tuple[str, str, str]] = []

    for name in type(inverter).response_decoder():
        measurement = sensor_map[name][1]
        unit = measurement.unit.value
        if measurement.is_monotonic:
            unit = f"{unit} [total]".strip()
        elif measurement.resets_daily:
            unit = f"{unit} [daily]".strip()
        rows.append((name, format_value(response.data[name]), unit))

    name_width = max(len(name) for name, _, _ in rows)
    value_width = max(len(value) for _, value, _ in rows)

    print(f"\nSensors ({len(rows)})")
    for name, value, unit in rows:
        print(f"  {name:<{name_width}}  {value:>{value_width}}  {unit}")


def raw_data(payload: bytes) -> List[Any]:
    """
    Pull the raw ``data`` array out of a payload.

    Normalised the same way ``ResponseParser.handle_response`` does it, so the
    indexes line up with what the decoder sees.
    """
    text = payload.decode("utf-8").replace(",,", ",0.0,").replace(",,", ",0.0,")
    document = {key.lower(): value for key, value in json.loads(text).items()}
    values = document.get("data", [])
    return values if isinstance(values, list) else []


def names_by_index(inverter: Inverter) -> Dict[int, List[str]]:
    """
    Map every raw index to the sensors reading it.

    ``sensor_map()`` collapses a packed sensor to its first index, so the
    decoder is walked directly to keep the other halves annotated too.
    """
    mapping: Dict[int, List[str]] = {}
    for name, spec in type(inverter).response_decoder().items():
        index_spec = spec[0]
        indexes = index_spec[0] if isinstance(index_spec, tuple) else (index_spec,)
        for index in indexes:
            mapping.setdefault(index, []).append(name)
    return mapping


def print_raw(inverter: Inverter, payload: bytes) -> None:
    values = raw_data(payload)
    mapping = names_by_index(inverter)
    index_width = len(str(len(values)))
    value_width = max((len(format_value(value)) for value in values), default=0)

    print(f"\nRaw data ({len(values)} values)")
    for index, value in enumerate(values):
        names = mapping.get(index)
        label = " -> " + ", ".join(names) if names else " (unmapped)"
        print(
            f"  [{index:>{index_width}}]  {format_value(value):>{value_width}}{label}"
        )


def save(path: str, payload: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(payload)
    print(f"\nRaw response written to {path}")


async def run(args: argparse.Namespace, host: str, port: int, pwd: str) -> int:
    print(
        f"Probing {host}:{port} — every known request shape is tried once, "
        "one second apart, so this takes a few seconds."
    )

    try:
        matched = await discover(host, port, pwd)
    except DiscoveryError as ex:
        print(
            f"\nNo model matched, or the inverter could not be reached.\n\n{ex}",
            file=sys.stderr,
        )
        return 1

    candidates = sorted(matched, key=lambda inverter: type(inverter).__name__)
    inverter = choose(candidates, host, port, pwd)

    try:
        payload = await inverter.http_client.request()
        response = inverter.parse_response(payload)
    except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
        print(f"\nCould not read from the inverter: {ex}", file=sys.stderr)
        return 1
    except InverterError as ex:
        print(f"\nCould not decode the response: {ex}", file=sys.stderr)
        return 1

    print_header(inverter, response, host, port, pwd)
    print_sensors(inverter, response)

    if args.raw:
        print_raw(inverter, payload)

    if args.save:
        save(args.save, payload)

    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover the Solax inverter answering on a host and print its data "
            "decoded through a matching model. Prompts for anything not given."
        )
    )
    parser.add_argument("--host", help="host, IP or full URL of the inverter")
    parser.add_argument("--port", type=int, help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("--pwd", help="inverter/dongle password, if it needs one")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="also dump the raw data array, marking mapped and unmapped indexes",
    )
    parser.add_argument(
        "--save",
        metavar="PATH",
        help="write the untouched JSON response to PATH",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show the library's probe logging"
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.getLogger().setLevel(logging.INFO if args.verbose else logging.WARNING)

    if args.save and os.path.exists(args.save):
        print(f"Refusing to overwrite existing file: {args.save}", file=sys.stderr)
        return 2

    try:
        host, port, pwd = resolve_target(args)
        return asyncio.run(run(args, host, port, pwd))
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
