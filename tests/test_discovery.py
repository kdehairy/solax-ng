import asyncio

import aiohttp
import pytest

import solaxng
from solaxng.discovery import REGISTRY, DiscoveryError, _probe_plan
from solaxng.endpoints import POST_BODY, POST_BODY_XFF, POST_QUERY, POST_QUERY_XFF
from solaxng.inverters import X1Boost, X1MiniV34, X3Ultra
from tests.samples.responses import X1_BOOST_RESPONSE

# pylint: disable=too-few-public-methods


class SlowHttpClient:
    def __init__(self, http_client, delay):
        self.http_client = http_client
        self.delay = delay

    async def request(self):
        await asyncio.sleep(self.delay)
        return await self.http_client.request()


class FailingHttpClient:
    async def request(self):
        raise aiohttp.ClientError("no inverter here")


class SlowEndpoint:
    """Answers correctly, but only after the staggering is long over."""

    def __init__(self, endpoint, delay):
        self.endpoint = endpoint
        self.delay = delay

    def build(self, host, port, pwd=""):
        return SlowHttpClient(self.endpoint.build(host, port, pwd), self.delay)


class FailingEndpoint:
    def build(self, *_args, **_kwargs):
        return FailingHttpClient()


class DelayedX1Boost(X1Boost):
    endpoints = (SlowEndpoint(POST_QUERY_XFF, 5),)  # type: ignore[assignment]


class DelayedFailedX1Boost(X1Boost):
    endpoints = (FailingEndpoint(),)  # type: ignore[assignment]


def test_probe_plan_groups_models_by_shared_endpoint():
    plan = _probe_plan([X1Boost, X1MiniV34, X3Ultra])

    assert list(plan) == [POST_QUERY_XFF, POST_BODY_XFF, POST_QUERY, POST_BODY]
    assert plan[POST_QUERY_XFF] == [X1Boost]
    assert plan[POST_BODY] == [X1MiniV34, X3Ultra]


def test_probe_plan_bounds_requests_by_endpoints_not_models():
    plan = _probe_plan(REGISTRY)

    assert len(REGISTRY) > len(plan)
    assert len(plan) == 5


@pytest.mark.asyncio
async def test_discovery(inverters_fixture):
    conn, inverter_class, _ = inverters_fixture
    inverters = await solaxng.discover(*conn)
    assert inverter_class in {type(inverter) for inverter in inverters}

    for inverter in inverters:
        if isinstance(inverter, inverter_class):
            data = await inverter.get_data()
            assert "X" * 7 in (data.inverter_serial_number or "X" * 7)
            assert data.serial_number == data.dongle_serial_number


@pytest.mark.asyncio
async def test_discovered_inverter_wraps_in_real_time_api(inverters_fixture):
    conn, inverter_class, _ = inverters_fixture

    if inverter_class is not X1Boost:
        pytest.skip()

    # discover() reports every model whose schema matched, which is not
    # always one; choosing among them is the caller's job, so pick the
    # wanted class deliberately instead of assuming the set is a single.
    inverters = await solaxng.discover(*conn)
    chosen = next(i for i in inverters if isinstance(i, inverter_class))
    rt_api = solaxng.RealTimeAPI(chosen)
    assert rt_api.inverter.__class__ is inverter_class


@pytest.mark.asyncio
async def test_model_answering_on_two_endpoints_is_reported_once(httpserver):
    httpserver.expect_request(uri="/", method="POST").respond_with_json(
        X1_BOOST_RESPONSE
    )

    inverters = await solaxng.discover(
        httpserver.host, httpserver.port, inverters=[X1Boost]
    )

    assert len(inverters) == 1
    found = next(iter(inverters))
    assert isinstance(found, X1Boost)
    assert found.http_client.query == "optType=ReadRealTimeData"


@pytest.mark.asyncio
async def test_model_is_not_reported_for_an_endpoint_it_never_declared(httpserver):
    httpserver.expect_request(
        uri="/", method="POST", headers={"X-Forwarded-For": "5.8.8.8"}
    ).respond_with_json(X1_BOOST_RESPONSE)

    inverters = await solaxng.discover(
        httpserver.host, httpserver.port, inverters=[X1Boost, X1MiniV34]
    )

    assert {type(inverter) for inverter in inverters} == {X1Boost}


@pytest.mark.asyncio
async def test_discovery_cancelled_error_while_staggering(
    inverters_fixture,
):
    conn, inverter_class, _ = inverters_fixture

    if inverter_class is not X1Boost:
        pytest.skip()

    task = asyncio.create_task(solaxng.discover(*conn))
    await asyncio.sleep(1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_discovery_cancelled_error_after_staggering(
    inverters_fixture,
):
    conn, inverter_class, _ = inverters_fixture

    if inverter_class is not X1Boost:
        pytest.skip()

    inverters = list(REGISTRY) + [DelayedX1Boost]

    task = asyncio.create_task(solaxng.discover(*conn, inverters=inverters))
    await asyncio.sleep(7)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_discovery_includes_slow_match_despite_a_faster_failure(
    inverters_fixture,
):
    conn, inverter_class, _ = inverters_fixture

    if inverter_class is not X1Boost:
        pytest.skip()

    inverters = await solaxng.discover(
        *conn,
        inverters=[DelayedX1Boost, DelayedFailedX1Boost],
    )
    assert DelayedX1Boost in {type(inverter) for inverter in inverters}


@pytest.mark.asyncio
async def test_discovery_no_host():
    with pytest.raises(DiscoveryError):
        await solaxng.discover("localhost", 2)


@pytest.mark.asyncio
async def test_discovery_no_host_with_pwd():
    with pytest.raises(DiscoveryError):
        await solaxng.discover("localhost", 2, "pwd")


@pytest.mark.asyncio
async def test_discovery_unknown_webserver(simple_http_fixture):
    with pytest.raises(DiscoveryError):
        await solaxng.discover(*simple_http_fixture)


@pytest.mark.asyncio
async def test_discovery_empty_inverter_class_iterable():
    with pytest.raises(DiscoveryError):
        await solaxng.discover("localhost", 2, inverters=[])
