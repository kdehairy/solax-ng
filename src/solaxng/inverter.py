from abc import abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import voluptuous as vol

from solaxng.endpoints import POST_BODY, POST_QUERY, EndpointConfig
from solaxng.inverter_http_client import InverterHttpClient
from solaxng.response_parser import InverterResponse, ResponseDecoder, ResponseParser
from solaxng.units import Measurement, Units


class InverterError(Exception):
    """Indicates error communicating with inverter"""


class Inverter:
    """Base wrapper around Inverter HTTP API"""

    @classmethod
    def response_decoder(cls) -> ResponseDecoder:
        """
        Inverter implementations should override
        this to return a decoding map
        """
        raise NotImplementedError()

    # pylint: enable=C0301
    _schema = vol.Schema({})  # type: vol.Schema

    endpoints: Tuple[EndpointConfig, ...] = (POST_QUERY, POST_BODY)

    def __init__(self, http_client: InverterHttpClient):
        self.manufacturer = "Solax"
        self.http_client = http_client

        schema = type(self).schema()
        response_decoder = type(self).response_decoder()
        dongle_serial_number_getter = type(self).dongle_serial_number_getter
        inverter_serial_number_getter = type(self).inverter_serial_number_getter
        self.response_parser = ResponseParser(
            schema,
            response_decoder,
            dongle_serial_number_getter,
            inverter_serial_number_getter,
        )

    @classmethod
    def build_all_variants(cls, host, port, pwd="") -> List["Inverter"]:
        return [cls(endpoint.build(host, port, pwd)) for endpoint in cls.endpoints]

    async def get_data(self) -> InverterResponse:
        try:
            data = await self.make_request()
        except aiohttp.ClientError as ex:
            msg = "Could not connect to inverter endpoint"
            raise InverterError(msg, str(self.__class__.__name__)) from ex
        except vol.Invalid as ex:
            msg = "Received malformed JSON from inverter"
            raise InverterError(msg, str(self.__class__.__name__)) from ex
        return data

    async def make_request(self) -> InverterResponse:
        """
        Return instance of 'InverterResponse'
        Raise exception if unable to get data
        """
        raw_response = await self.http_client.request()
        return self.response_parser.handle_response(raw_response)

    @classmethod
    def sensor_map(cls) -> Dict[str, Tuple[int, Measurement]]:
        """
        Return sensor map
        Warning, HA depends on this
        """
        sensors: Dict[str, Tuple[int, Measurement]] = {}
        for name, mapping in cls.response_decoder().items():
            unit = Measurement(Units.NONE)

            idx, unit_or_measurement, *_ = mapping

            if isinstance(unit_or_measurement, Units):
                unit = Measurement(unit_or_measurement)
            else:
                unit = unit_or_measurement
            if isinstance(idx, tuple):
                sensor_indexes = idx[0]
                first_sensor_index = sensor_indexes[0]
                idx = first_sensor_index
            sensors[name] = (idx, unit)
        return sensors

    @classmethod
    def schema(cls) -> vol.Schema:
        """
        Return schema
        """
        return cls._schema

    @classmethod
    def dongle_serial_number_getter(cls, response: Dict[str, Any]) -> Optional[str]:
        return response["sn"]

    @classmethod
    @abstractmethod
    def inverter_serial_number_getter(cls, response: Dict[str, Any]) -> Optional[str]:
        raise NotImplementedError  # pragma: no cover

    def __str__(self) -> str:
        return f"{self.__class__.__name__}::{self.http_client}"
