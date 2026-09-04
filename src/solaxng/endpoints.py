"""
The HTTP request shapes a Solax inverter's local endpoint is known to answer.

Each `EndpointConfig` is a frozen, hashable value object, which lets
discovery use one as a dict key and probe it exactly once no matter how
many models declare it.
"""

from dataclasses import dataclass, field
from typing import Tuple

from solaxng.inverter_http_client import InverterHttpClient, Method
from solaxng.utils import to_url

__all__ = (
    "EndpointConfig",
    "ENDPOINT_REGISTRY",
    "POST_QUERY",
    "POST_BODY",
    "POST_QUERY_XFF",
    "POST_BODY_XFF",
    "GET_REALTIME_HTM",
)

HeaderItems = Tuple[Tuple[str, str], ...]

X_FORWARDED_FOR: HeaderItems = (("X-Forwarded-For", "5.8.8.8"),)


@dataclass(frozen=True)
class EndpointConfig:
    """
    The HTTP request shapes a Solax inverter's local endpoint is known to answer.

    Each `EndpointConfig` is a frozen, hashable value object, which lets
    discovery use one as a dict key and probe it exactly once no matter how
    many models declare it.
    """

    name: str
    method: Method
    path: str = ""
    params_in_query: bool = True
    send_params: bool = True
    use_pwd: bool = True
    headers: HeaderItems = field(default=())

    def build(self, host, port, pwd="") -> InverterHttpClient:
        http_client = InverterHttpClient(
            url=to_url(host, port) + self.path,
            method=self.method,
            pwd=pwd if self.use_pwd else "",
        )

        if self.send_params:
            if self.params_in_query:
                http_client = http_client.with_default_query()
            else:
                http_client = http_client.with_default_data()

        if self.headers:
            http_client = http_client.with_headers(dict(self.headers))

        return http_client

    def __str__(self) -> str:
        return self.name


POST_QUERY = EndpointConfig(
    name="post-query",
    method=Method.POST,
)

POST_BODY = EndpointConfig(
    name="post-body",
    method=Method.POST,
    params_in_query=False,
)

POST_QUERY_XFF = EndpointConfig(
    name="post-query-xff",
    method=Method.POST,
    headers=X_FORWARDED_FOR,
)

POST_BODY_XFF = EndpointConfig(
    name="post-body-xff",
    method=Method.POST,
    params_in_query=False,
    headers=X_FORWARDED_FOR,
)

GET_REALTIME_HTM = EndpointConfig(
    name="get-realtimedata-htm",
    method=Method.GET,
    path="api/realTimeData.htm",
    send_params=False,
    use_pwd=False,
)

ENDPOINT_REGISTRY: Tuple[EndpointConfig, ...] = (
    POST_QUERY,
    POST_BODY,
    POST_QUERY_XFF,
    POST_BODY_XFF,
    GET_REALTIME_HTM,
)
