import asyncio
import logging
import sys
from typing import Dict, List, Sequence, Set, Tuple, Type, TypedDict

from solaxng.endpoints import EndpointConfig
from solaxng.inverter import Inverter, InverterError

__all__ = ("discover", "DiscoveryKeywords", "DiscoveryError")

if sys.version_info >= (3, 10):
    from importlib.metadata import entry_points
else:
    from importlib_metadata import entry_points  # pragma: no cover

if sys.version_info >= (3, 11):
    from typing import Unpack
else:
    from typing_extensions import Unpack  # pragma: no cover

# registry of inverters
REGISTRY: Tuple[Type[Inverter], ...] = tuple(
    dict.fromkeys(
        loaded
        for ep in entry_points(group="solaxng.inverter")
        if issubclass(loaded := ep.load(), Inverter)
    )
)

logging.basicConfig(level=logging.INFO)

STAGGER_SECONDS = 1


class DiscoveryKeywords(TypedDict, total=False):
    inverters: Sequence[Type[Inverter]]


ProbePlan = Dict[EndpointConfig, List[Type[Inverter]]]


def _probe_plan(inverters: Sequence[Type[Inverter]]) -> ProbePlan:
    """
    Group the models by the endpoint they declare.

    Only one inverter is answering, so an endpoint several models share is
    worth probing once. The plan keeps insertion order, which makes the
    first endpoint a model declares the one it is built on when it matches.
    """
    plan: ProbePlan = {}
    for cls in inverters:
        for endpoint in cls.endpoints:
            plan.setdefault(endpoint, []).append(cls)
    return plan


async def _probe(http_client, delay):
    await asyncio.sleep(delay)
    logging.info("Probing %s", http_client)
    return await http_client.request()


async def discover(
    host, port, pwd="", **kwargs: Unpack[DiscoveryKeywords]
) -> Set[Inverter]:
    plan = _probe_plan(kwargs.get("inverters", REGISTRY))

    if not plan:
        raise DiscoveryError("No inverters to try to discover")

    clients = {endpoint: endpoint.build(host, port, pwd) for endpoint in plan}

    # stagger HTTP requests to prevent accidental Denial Of Service
    responses = await asyncio.gather(
        *(
            _probe(clients[endpoint], position * STAGGER_SECONDS)
            for position, endpoint in enumerate(plan)
        ),
        return_exceptions=True,
    )

    failures: List[BaseException] = []
    discovered: Dict[Type[Inverter], Inverter] = {}

    for endpoint, response in zip(plan, responses):
        if isinstance(response, BaseException):
            failures.append(response)
            continue

        for cls in plan[endpoint]:
            if cls in discovered:
                continue

            inverter = cls(clients[endpoint])
            try:
                inverter.parse_response(response)
            except InverterError as ex:
                failures.append(ex)
                continue

            discovered[cls] = inverter

    if discovered:
        logging.info("Discovered inverters: %s", [str(i) for i in discovered.values()])
        return set(discovered.values())

    raise DiscoveryError(
        "Unable to connect to the inverter at "
        f"host={host} port={port}, or your inverter is not supported yet.\n"
        "Please see https://github.com/squishykid/solax/wiki/DiscoveryError\n"
        f"Failures={str(failures)}"
    )


class DiscoveryError(Exception):
    """Raised when unable to discover inverter"""
