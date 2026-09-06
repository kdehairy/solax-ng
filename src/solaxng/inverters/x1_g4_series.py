from typing import Any, Dict, Optional

import voluptuous as vol

from solaxng.endpoints import POST_BODY_XFF, POST_QUERY_XFF
from solaxng.inverter import Inverter
from solaxng.units import DailyTotal, Total, Units
from solaxng.utils import div10, div100, pack_u16, to_signed


class X1G4Series(Inverter):
    """
    Tested with
    X1-Boost gen 4 with Pocket WiFi 3.009.03
    and
    X1-Mini gen 4 WIFI+LAN 1.001.20

    Includes X-Forwarded-For for direct LAN API access
    """

    endpoints = (POST_QUERY_XFF, POST_BODY_XFF)

    @classmethod
    def friendly_name(cls) -> str:
        return "X1 G4 Series"

    # pylint: disable=duplicate-code
    _schema = vol.Schema(
        {
            vol.Required("type", "type"): vol.All(int, vol.Any(18, 22)),
            vol.Required(
                "sn",
            ): str,
            vol.Required("ver"): str,
            vol.Required("data"): vol.Schema(
                vol.All([vol.Coerce(float)], vol.Length(min=100, max=100))
            ),
            vol.Required("information"): vol.Schema(
                vol.All(vol.Length(min=10, max=10))
            ),
        },
        extra=vol.REMOVE_EXTRA,
    )

    @classmethod
    def response_decoder(cls):
        return {
            "AC Voltage": (0, Units.V, div10),
            "AC Output Current": (1, Units.A, div10),
            "AC Output Power": (3, Units.W),
            "PV1 Voltage": (4, Units.V, div10),
            "PV2 Voltage": (5, Units.V, div10),
            "PV1 Current": (8, Units.A, div10),
            "PV2 Current": (9, Units.A, div10),
            "PV1 Power": (13, Units.W),
            "PV2 Power": (14, Units.W),
            "AC Frequency": (2, Units.HZ, div100),
            "Total Generated Energy": (pack_u16(19, 20), Total(Units.KWH), div10),
            "Today's Generated Energy": (21, DailyTotal(Units.KWH), div10),
            "Exported Power": (pack_u16(72, 73), Units.W, to_signed),
            "Total Export Energy": (pack_u16(74, 75), Total(Units.KWH), div100),
            "Total Import Energy": (pack_u16(76, 77), Total(Units.KWH), div100),
        }

    @classmethod
    def inverter_serial_number_getter(cls, response: Dict[str, Any]) -> Optional[str]:
        return response["information"][2]
