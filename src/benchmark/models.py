from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path


class PortDirection(StrEnum):
    INPUT = auto()
    OUTPUT = auto()
    INOUT = auto()


class HDLType(StrEnum):
    VERILOG = auto()
    SYSTEMVERILOG = auto()
    VHDL = auto()


class MutationType(StrEnum):
    BUG_FIX = auto()
    NEW_FEATURE = auto()
    TIMING_OPT = auto()
    AREA_OPT = auto()
    POWER_OPT = auto()
    FSM_REFACTOR = auto()
    PIPELINE_INSERT = auto()
    INTERFACE_CHANGE = auto()
    CLOCK_DOMAIN_FIX = auto()
    RESET_LOGIC_FIX = auto()


MUTATION_DESCRIPTIONS: dict[MutationType, str] = {
    MutationType.BUG_FIX: (
        "Fix a functional bug in the RTL: off-by-one counter, wrong state transition, "
        "missing reset for a register, incorrect bit-slice, or wrong sensitivity list."
    ),
    MutationType.NEW_FEATURE: (
        "Add a small new feature: a new output status register, a configuration register "
        "accessible via an existing interface, or a bypass/debug mux."
    ),
    MutationType.TIMING_OPT: (
        "Insert a pipeline register on a long combinational path to improve timing. "
        "Add a register stage between two existing modules."
    ),
    MutationType.AREA_OPT: (
        "Reduce area by sharing a multiplier/adder between two states of an FSM, "
        "or replacing parallel logic with a time-multiplexed implementation."
    ),
    MutationType.POWER_OPT: (
        "Add clock gating enable logic for a datapath block, or add operand isolation "
        "to reduce dynamic power when a module is idle."
    ),
    MutationType.FSM_REFACTOR: (
        "Refactor a state machine: add a missing idle/error state, fix an unreachable state, "
        "split a complex state into sub-states, or change encoding."
    ),
    MutationType.PIPELINE_INSERT: (
        "Insert one pipeline stage in a datapath to break a critical path. "
        "Adjust valid/ready handshake signals accordingly."
    ),
    MutationType.INTERFACE_CHANGE: (
        "Modify a module interface: widen a data bus, add a valid/ready handshake, "
        "or add a new control port. Propagate changes through the hierarchy."
    ),
    MutationType.CLOCK_DOMAIN_FIX: (
        "Fix a clock domain crossing issue: add a synchronizer for a signal "
        "crossing from one clock domain to another, or add a FIFO wrapper."
    ),
    MutationType.RESET_LOGIC_FIX: (
        "Fix reset logic: convert async reset to sync reset for specific registers, "
        "add missing reset to a state register, or fix reset polarity."
    ),
}


@dataclass
class VerilogPort:
    name: str
    direction: PortDirection
    width: int = 1
    msb: int = 0
    lsb: int = 0
    is_clock: bool = False
    is_reset: bool = False


@dataclass
class VerilogModule:
    name: str
    file_path: Path
    ports: list[VerilogPort] = field(default_factory=list)
    instances: list[str] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass
class ClockSpec:
    port_name: str
    clock_name: str
    period_ns: float
    waveform: tuple[float, float] | None = None


@dataclass
class ClockGroupSpec:
    group_type: str  # "asynchronous" or "exclusive"
    groups: list[list[str]] = field(default_factory=list)


@dataclass
class SDCParams:
    clocks: list[ClockSpec] = field(default_factory=list)
    clock_groups: list[ClockGroupSpec] = field(default_factory=list)
    reset_ports: list[str] = field(default_factory=list)
    max_fanout: int = 32
    max_transition_ns: float = 0.8
    clock_uncertainty_setup_ns: float = 0.3
    clock_uncertainty_hold_ns: float = 0.2
    clock_transition_ns: float = 0.6
    io_delay_ns: float = 0.5
    non_data_ports: list[str] = field(default_factory=list)


@dataclass
class DesignAnalysis:
    top_module: VerilogModule
    all_modules: dict[str, VerilogModule]
    clock_ports: list[VerilogPort]
    reset_ports: list[VerilogPort]
    file_order: list[Path]
    rtl_dir_name: str
    hdl_type: HDLType = HDLType.VERILOG
