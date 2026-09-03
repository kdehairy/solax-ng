import asyncio

import pytest

import solaxng
from solaxng import InverterResponse
from solaxng.discovery import REGISTRY, DiscoveryError
from solaxng.inverter import InverterError
from solaxng.inverters import X1Boost


class DelayedX1Boost(X1Boost):
    async def get_data(self) -> InverterResponse:
        await asyncio.sleep(10)
        return await super().get_data()


class DelayedFailedX1Boost(X1Boost):
    async def make_request(self) -> InverterResponse:
        await asyncio.sleep(5)
        raise InverterError


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

    inverters = set(REGISTRY)
    inverters.add(DelayedX1Boost)

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
