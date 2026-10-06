"""HAL blocks: operations over terminals and rules spanning several terminals."""

from hil.blocks.analog import AnalogBlock
from hil.blocks.comm import CommBlock
from hil.blocks.debug import DebugBlock
from hil.blocks.digital import DigitalBlock
from hil.blocks.faults import FaultMatrix
from hil.blocks.power import PowerBlock

__all__ = ["AnalogBlock", "CommBlock", "DebugBlock", "DigitalBlock", "FaultMatrix", "PowerBlock"]
