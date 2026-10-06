"""Waveshare Modbus RTU Relay 32-ch (driver ``waveshare_relay32``).

Relay i is coil i, written with function 15 and read with function 1, as the vendor
documents it. The map is not verified on hardware yet; ``coil_base`` and ``write`` in
the station file adapt it without a code change.
"""

from hil.drivers.modbus_relay import ModbusRelayModule
from hil.drivers.registry import register_driver


@register_driver("waveshare_relay32")
class WaveshareRelay32(ModbusRelayModule):
    """32 relays, each with one NO and one NC contact."""
