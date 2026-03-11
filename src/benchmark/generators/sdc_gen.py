from __future__ import annotations

import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from benchmark.config import BenchmarkConfig
from benchmark.llm import call_llm, extract_json_from_response
from benchmark.models import (
    ClockGroupSpec,
    ClockSpec,
    DesignAnalysis,
    PortDirection,
    SDCParams,
)

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

SDC_SYSTEM_PROMPT = """\
You are an expert IC design constraint engineer. Given RTL design information, \
you determine the correct SDC (Synopsys Design Constraints) parameters.

Rules:
1. Clock period estimation based on design complexity:
   - Simple combinational / small FSM: 5-10 ns
   - Medium datapath / accelerator: 10-20 ns
   - Complex pipelined processor: 3-8 ns
   - High-speed serial / DSP: 1-5 ns
2. Multiple independent clocks MUST have clock_groups (asynchronous or exclusive).
3. Asynchronous resets MUST have set_false_path.
4. IO delay is typically 2-5% of clock period, minimum 0.3 ns.
5. Return ONLY valid JSON matching the schema below. No explanation outside JSON."""

SDC_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "clocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "port_name": {"type": "string"},
                    "clock_name": {"type": "string"},
                    "period_ns": {"type": "number"},
                },
                "required": ["port_name", "clock_name", "period_ns"],
            },
        },
        "clock_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group_type": {"type": "string", "enum": ["asynchronous", "exclusive"]},
                    "groups": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                },
            },
        },
        "reset_ports": {"type": "array", "items": {"type": "string"}},
        "max_fanout": {"type": "integer"},
        "max_transition_ns": {"type": "number"},
        "clock_uncertainty_setup_ns": {"type": "number"},
        "clock_uncertainty_hold_ns": {"type": "number"},
        "clock_transition_ns": {"type": "number"},
        "io_delay_ns": {"type": "number"},
    },
    "required": ["clocks", "reset_ports"],
}


def _build_port_table(analysis: DesignAnalysis) -> str:
    lines = []
    for p in analysis.top_module.ports:
        width_str = f"[{p.msb}:{p.lsb}]" if p.width > 1 else ""
        flags = []
        if p.is_clock:
            flags.append("CLOCK_CANDIDATE")
        if p.is_reset:
            flags.append("RESET_CANDIDATE")
        flag_str = f"  <- {', '.join(flags)}" if flags else ""
        lines.append(f"  {p.direction.value:6s} {width_str:>8s} {p.name}{flag_str}")
    return "\n".join(lines)


def _build_hierarchy_summary(analysis: DesignAnalysis) -> str:
    lines = [f"Top: {analysis.top_module.name}"]
    for inst in analysis.top_module.instances:
        mod = analysis.all_modules.get(inst)
        port_count = len(mod.ports) if mod else "?"
        lines.append(f"  └─ {inst} ({port_count} ports)")
    return "\n".join(lines)


def _build_user_prompt(analysis: DesignAnalysis) -> str:
    port_table = _build_port_table(analysis)
    hierarchy = _build_hierarchy_summary(analysis)

    clock_names = [p.name for p in analysis.clock_ports]
    reset_names = [p.name for p in analysis.reset_ports]

    return f"""\
## Design Information
- Top Module: {analysis.top_module.name}
- Total modules: {len(analysis.all_modules)}
- HDL type: {analysis.hdl_type.value}

## Top Module Ports
{port_table}

## Module Hierarchy
{hierarchy}

## Detected Clock Candidates: {clock_names or 'NONE - you must identify from ports'}
## Detected Reset Candidates: {reset_names or 'NONE'}

## Output JSON Schema
{json.dumps(SDC_JSON_SCHEMA, indent=2)}

Return ONLY the JSON object. No markdown, no explanation."""


def _parse_sdc_response(raw: str, analysis: DesignAnalysis) -> SDCParams:
    data = extract_json_from_response(raw)

    clocks = [
        ClockSpec(
            port_name=c["port_name"],
            clock_name=c["clock_name"],
            period_ns=float(c["period_ns"]),
        )
        for c in data.get("clocks", [])
    ]

    if not clocks and analysis.clock_ports:
        for cp in analysis.clock_ports:
            clocks.append(ClockSpec(
                port_name=cp.name,
                clock_name=cp.name,
                period_ns=10.0,
            ))

    clock_groups = [
        ClockGroupSpec(
            group_type=g.get("group_type", "asynchronous"),
            groups=g.get("groups", []),
        )
        for g in data.get("clock_groups", [])
    ]

    reset_ports = data.get("reset_ports", [])
    if not reset_ports:
        reset_ports = [p.name for p in analysis.reset_ports]

    non_data_ports = list({
        *[c.port_name for c in clocks],
        *reset_ports,
    })

    return SDCParams(
        clocks=clocks,
        clock_groups=clock_groups,
        reset_ports=reset_ports,
        max_fanout=data.get("max_fanout", 32),
        max_transition_ns=data.get("max_transition_ns", 0.8),
        clock_uncertainty_setup_ns=data.get("clock_uncertainty_setup_ns", 0.3),
        clock_uncertainty_hold_ns=data.get("clock_uncertainty_hold_ns", 0.2),
        clock_transition_ns=data.get("clock_transition_ns", 0.6),
        io_delay_ns=data.get("io_delay_ns", 0.5),
        non_data_ports=non_data_ports,
    )


def render_sdc(params: SDCParams) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("func_sdc.j2")

    rendered = template.render(
        clocks=[
            {"port_name": c.port_name, "clock_name": c.clock_name, "period_ns": c.period_ns}
            for c in params.clocks
        ],
        clock_groups=[
            {"group_type": g.group_type, "groups": g.groups}
            for g in params.clock_groups
        ],
        reset_ports=params.reset_ports,
        max_fanout=params.max_fanout,
        max_transition_ns=params.max_transition_ns,
        clock_uncertainty_setup_ns=params.clock_uncertainty_setup_ns,
        clock_uncertainty_hold_ns=params.clock_uncertainty_hold_ns,
        clock_transition_ns=params.clock_transition_ns,
        io_delay_ns=params.io_delay_ns,
        non_data_ports=params.non_data_ports,
    )

    lines = rendered.split("\n")
    cleaned = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 1:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(line)

    while cleaned and cleaned[-1].strip() == "":
        cleaned.pop()
    while cleaned and cleaned[0].strip() == "":
        cleaned.pop(0)

    return "\n".join(cleaned) + "\n"


async def generate_sdc(
    analysis: DesignAnalysis,
    config: BenchmarkConfig,
    clock_period_override: float | None = None,
) -> str:
    user_prompt = _build_user_prompt(analysis)

    raw_response = await call_llm(
        config=config,
        system_prompt=SDC_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.2,
        json_mode=True,
    )

    logger.debug("LLM SDC response: %s", raw_response)

    params = _parse_sdc_response(raw_response, analysis)

    if clock_period_override and params.clocks:
        ratio = clock_period_override / params.clocks[0].period_ns
        for c in params.clocks:
            c.period_ns = round(c.period_ns * ratio, 2)
        params.io_delay_ns = round(max(0.3, clock_period_override * 0.03), 2)

    return render_sdc(params)
