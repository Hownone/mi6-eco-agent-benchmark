from __future__ import annotations

import re
from pathlib import Path

from benchmark.models import HDLType, PortDirection, VerilogModule, VerilogPort

# ---------- regex patterns for Verilog/SV ----------

# Strip // and /* */ comments, preserving string literals
_LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# module <name> [#(params)] (ports); ... endmodule
_MODULE_RE = re.compile(
    r"\bmodule\s+(\w+)"
    r"(?:\s*#\s*\((?P<params>[^)]*)\))?"
    r"\s*(?:\((?P<ports>[^)]*)\))?"
    r"\s*;",
    re.DOTALL,
)

_ENDMODULE_RE = re.compile(r"\bendmodule\b")

# ANSI-style port in module header: input/output/inout [wire/reg/logic] [signed] [N:M] name
_ANSI_PORT_RE = re.compile(
    r"\b(input|output|inout)\s+"
    r"(?:wire|reg|logic|signed|\s)*"
    r"(?:\[(\d+):(\d+)\]\s*)?"
    r"(\w+)"
)

# Non-ANSI port declarations inside module body
_BODY_PORT_RE = re.compile(
    r"^\s*(input|output|inout)\s+"
    r"(?:wire|reg|logic|signed|\s)*"
    r"(?:\[(\d+):(\d+)\]\s*)?"
    r"(.+?)\s*;",
    re.MULTILINE,
)

# Module instantiation: <module_name> [#(params)] <inst_name> (
_INSTANCE_RE = re.compile(
    r"\b(\w+)\s+(?:#\s*\([^)]*\)\s*)?(\w+)\s*\(",
)

# Parameter: parameter <name> = <value>
_PARAM_RE = re.compile(r"\bparameter\s+(?:\w+\s+)?(\w+)\s*=\s*([^,;)]+)")

# VHDL: entity <name> is ... end [entity] [<name>];
_VHDL_ENTITY_RE = re.compile(
    r"\bentity\s+(\w+)\s+is\b(.*?)\bend\s+(?:entity\s+)?\w*\s*;",
    re.DOTALL | re.IGNORECASE,
)

_VHDL_PORT_RE = re.compile(
    r"(\w+)\s*:\s*(in|out|inout|buffer)\s+"
    r"(?:std_logic_vector\s*\(\s*(\d+)\s+downto\s+(\d+)\s*\)|std_logic|\w+)",
    re.IGNORECASE,
)

# Verilog keywords that can appear before an identifier but are NOT module instantiations
_VERILOG_KEYWORDS = frozenset({
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "logic",
    "integer", "real", "realtime", "time", "genvar", "parameter", "localparam",
    "assign", "always", "always_ff", "always_comb", "always_latch", "initial",
    "begin", "end", "if", "else", "case", "casex", "casez", "default",
    "for", "while", "repeat", "forever", "generate", "endgenerate",
    "function", "endfunction", "task", "endtask", "return",
    "posedge", "negedge", "or", "and", "not", "xor", "nand", "nor",
    "buf", "pullup", "pulldown", "supply0", "supply1", "tri", "wand", "wor",
    "signed", "unsigned", "specify", "endspecify", "table", "endtable",
    "primitive", "endprimitive", "defparam", "event",
    "typedef", "struct", "enum", "union", "interface", "endinterface",
    "class", "endclass", "package", "endpackage", "import",
    "assert", "property", "sequence", "covergroup",
})

# Common clock / reset name patterns
_CLOCK_PATTERNS = re.compile(
    r"^(clk|clock|sysclk|mclk|pclk|hclk|fclk|aclk|bclk|rclk|wclk|tck)"
    r"|"
    r"(clk|clock|_clk_i|_clk_o|clk_i|clk_o)$",
    re.IGNORECASE,
)

_RESET_PATTERNS = re.compile(
    r"^(rst|reset|rstn|nrst|arst|srst)"
    r"|"
    r"(rst|reset|rstn|rst_n|_rst_i|_rst_ni|reset_i|reset_n|reset_ni)$",
    re.IGNORECASE,
)


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT.sub("", text)
    text = _LINE_COMMENT.sub("", text)
    return text


def _parse_direction(s: str) -> PortDirection:
    s = s.lower().strip()
    if s == "input" or s == "in":
        return PortDirection.INPUT
    if s == "output" or s == "out":
        return PortDirection.OUTPUT
    return PortDirection.INOUT


def _is_clock_candidate(port: VerilogPort) -> bool:
    if port.direction != PortDirection.INPUT:
        return False
    if port.width != 1:
        return False
    return bool(_CLOCK_PATTERNS.search(port.name))


def _is_reset_candidate(port: VerilogPort) -> bool:
    if port.direction != PortDirection.INPUT:
        return False
    if port.width != 1:
        return False
    return bool(_RESET_PATTERNS.search(port.name))


def _parse_ansi_ports(port_text: str) -> list[VerilogPort]:
    ports: list[VerilogPort] = []
    for m in _ANSI_PORT_RE.finditer(port_text):
        direction = _parse_direction(m.group(1))
        msb = int(m.group(2)) if m.group(2) else 0
        lsb = int(m.group(3)) if m.group(3) else 0
        width = abs(msb - lsb) + 1
        name = m.group(4)
        port = VerilogPort(
            name=name, direction=direction, width=width, msb=msb, lsb=lsb,
        )
        port.is_clock = _is_clock_candidate(port)
        port.is_reset = _is_reset_candidate(port)
        ports.append(port)
    return ports


def _parse_body_ports(body: str) -> list[VerilogPort]:
    ports: list[VerilogPort] = []
    for m in _BODY_PORT_RE.finditer(body):
        direction = _parse_direction(m.group(1))
        msb = int(m.group(2)) if m.group(2) else 0
        lsb = int(m.group(3)) if m.group(3) else 0
        width = abs(msb - lsb) + 1
        names_str = m.group(4)
        for raw_name in names_str.split(","):
            name = raw_name.strip()
            if not name or not re.match(r"^\w+$", name):
                continue
            port = VerilogPort(
                name=name, direction=direction, width=width, msb=msb, lsb=lsb,
            )
            port.is_clock = _is_clock_candidate(port)
            port.is_reset = _is_reset_candidate(port)
            ports.append(port)
    return ports


def _parse_instances(body: str, known_modules: set[str]) -> list[str]:
    instances: list[str] = []
    for m in _INSTANCE_RE.finditer(body):
        mod_name = m.group(1)
        if mod_name in _VERILOG_KEYWORDS:
            continue
        if mod_name in known_modules or not mod_name.startswith(("$", "#")):
            instances.append(mod_name)
    return instances


def _parse_params(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _PARAM_RE.finditer(text)}


def parse_verilog_file(file_path: Path) -> list[VerilogModule]:
    raw = file_path.read_text(encoding="utf-8", errors="ignore")
    clean = _strip_comments(raw)

    modules: list[VerilogModule] = []

    module_starts = list(_MODULE_RE.finditer(clean))
    module_ends = list(_ENDMODULE_RE.finditer(clean))

    for i, m_start in enumerate(module_starts):
        mod_name = m_start.group(1)

        end_pos = len(clean)
        for m_end in module_ends:
            if m_end.start() > m_start.end():
                end_pos = m_end.start()
                break

        body = clean[m_start.end():end_pos]

        ports: list[VerilogPort] = []
        port_text = m_start.group("ports")
        if port_text and _ANSI_PORT_RE.search(port_text):
            ports = _parse_ansi_ports(port_text)
        else:
            ports = _parse_body_ports(body)

        params = _parse_params(body)
        if m_start.group("params"):
            params.update(_parse_params(m_start.group("params")))

        modules.append(VerilogModule(
            name=mod_name,
            file_path=file_path,
            ports=ports,
            instances=[],
            parameters=params,
        ))

    return modules


def parse_vhdl_file(file_path: Path) -> list[VerilogModule]:
    raw = file_path.read_text(encoding="utf-8", errors="ignore")
    raw_stripped = re.sub(r"--.*$", "", raw, flags=re.MULTILINE)

    modules: list[VerilogModule] = []

    for m in _VHDL_ENTITY_RE.finditer(raw_stripped):
        entity_name = m.group(1)
        entity_body = m.group(2)

        ports: list[VerilogPort] = []
        for pm in _VHDL_PORT_RE.finditer(entity_body):
            name = pm.group(1)
            direction = _parse_direction(pm.group(2))
            msb = int(pm.group(3)) if pm.group(3) else 0
            lsb = int(pm.group(4)) if pm.group(4) else 0
            width = abs(msb - lsb) + 1

            port = VerilogPort(
                name=name, direction=direction, width=width, msb=msb, lsb=lsb,
            )
            port.is_clock = _is_clock_candidate(port)
            port.is_reset = _is_reset_candidate(port)
            ports.append(port)

        modules.append(VerilogModule(
            name=entity_name,
            file_path=file_path,
            ports=ports,
        ))

    return modules


def detect_hdl_type(file_path: Path) -> HDLType:
    suffix = file_path.suffix.lower()
    if suffix in (".vhd", ".vhdl"):
        return HDLType.VHDL
    if suffix == ".sv":
        return HDLType.SYSTEMVERILOG
    return HDLType.VERILOG


def parse_hdl_file(file_path: Path) -> list[VerilogModule]:
    hdl_type = detect_hdl_type(file_path)
    if hdl_type == HDLType.VHDL:
        return parse_vhdl_file(file_path)
    return parse_verilog_file(file_path)
