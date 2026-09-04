"""
The endpoint registry describes how each known firmware wants the
real-time-data request framed. These tests pin the exact bytes each config
puts on the wire, since discovery's ability to identify a model depends on
the inverter answering the request shape it expects.
"""

import pytest

from solaxng.endpoints import (
    ENDPOINT_REGISTRY,
    GET_REALTIME_HTM,
    POST_BODY,
    POST_BODY_XFF,
    POST_QUERY,
    POST_QUERY_XFF,
    EndpointConfig,
)
from solaxng.inverter_http_client import Method

X_FORWARDED = {"X-Forwarded-For": "5.8.8.8"}


def test_post_query_puts_params_in_the_query_string():
    client = POST_QUERY.build("localhost", 80)

    assert client.url == "http://localhost:80/"
    assert client.method is Method.POST
    assert client.query == "optType=ReadRealTimeData"
    assert client.data is None
    assert client.headers == {}


def test_post_body_puts_params_in_the_body():
    client = POST_BODY.build("localhost", 80)

    assert client.url == "http://localhost:80/"
    assert client.method is Method.POST
    assert client.query == ""
    assert client.data == "optType=ReadRealTimeData"
    assert client.headers == {}


@pytest.mark.parametrize("endpoint", [POST_QUERY_XFF, POST_BODY_XFF])
def test_xff_endpoints_send_the_forwarded_header(endpoint):
    assert endpoint.build("localhost", 80).headers == X_FORWARDED


def test_get_realtime_htm_sends_no_params_on_its_own_path():
    client = GET_REALTIME_HTM.build("localhost", 80)

    assert client.url == "http://localhost:80/api/realTimeData.htm"
    assert client.method is Method.GET
    assert client.query == ""
    assert client.data is None
    assert client.headers == {}


def test_password_goes_into_the_query_string():
    client = POST_QUERY.build("localhost", 80, "s3cret")

    assert client.pwd == "s3cret"
    assert client.query == "optType=ReadRealTimeData&pwd=s3cret&"


def test_password_goes_into_the_body():
    client = POST_BODY.build("localhost", 80, "s3cret")

    assert client.pwd == "s3cret"
    assert client.data == "optType=ReadRealTimeData&pwd=s3cret"


def test_endpoint_that_ignores_the_password_drops_it():
    """
    The X-Hybrid dongle has no password concept; handing it one would
    change the request it answers.
    """
    client = GET_REALTIME_HTM.build("localhost", 80, "s3cret")

    assert client.pwd == ""
    assert client.query == ""
    assert client.data is None


def test_configs_are_hashable_so_discovery_can_probe_each_once():
    duplicate = EndpointConfig(name="post-query", method=Method.POST)

    assert duplicate == POST_QUERY
    assert len({POST_QUERY, duplicate}) == 1
    assert len(set(ENDPOINT_REGISTRY)) == len(ENDPOINT_REGISTRY)


def test_config_is_named_for_logging():
    assert str(POST_BODY_XFF) == "post-body-xff"
