from __future__ import annotations

import re
from pathlib import Path

from benchmark.models import (
    DesignAnalysis,
    HDLType,
    PortDirection,
    VerilogModule,
    VerilogPort,
)
from benchmark.rtl_analyzer.verilog_parser import (
    _INSTANCE_RE,
    _VERILOG_KEYWORDS,
    _strip_comments,
    detect_hdl_type,
    parse_hdl_file,
)


_EXCLUDED_DIRS = {"design", "data", "sim", "tb", "testbench", "verify", ".git", "__pycache__"}


def discover_rtl_files(rtl_dir: Path) -> list[Path]:
    extensions = {".v", ".sv", ".vhd", ".vhdl"}

    for candidate in ["rtl", "RTL", "src", "hdl"]:
        subdir = rtl_dir / candidate
        if subdir.is_dir():
            return _collect_hdl_files(subdir, extensions)

    return _collect_hdl_files(rtl_dir, extensions)


def _collect_hdl_files(base: Path, extensions: set[str]) -> list[Path]:
    files: list[Path] = []
    for f in sorted(base.rglob("*")):
        if any(part in _EXCLUDED_DIRS for part in f.relative_to(base).parts):
            continue
        if f.is_file() and f.suffix.lower() in extensions:
            files.append(f)
    return files


def _detect_rtl_subdir(rtl_dir: Path) -> str:
    for candidate in ["rtl", "RTL", "src", "hdl"]:
        if (rtl_dir / candidate).is_dir():
            return candidate

    hdl_extensions = {".v", ".sv", ".vhd", ".vhdl"}
    for f in rtl_dir.iterdir():
        if f.is_file() and f.suffix.lower() in hdl_extensions:
            return "."

    return "rtl"


def _resolve_instances(
    body: str, all_module_names: set[str]
) -> list[str]:
    instances: list[str] = []
    seen: set[str] = set()

    for m in _INSTANCE_RE.finditer(body):
        mod_name = m.group(1)
        if mod_name in _VERILOG_KEYWORDS:
            continue
        if mod_name not in all_module_names:
            continue
        if mod_name not in seen:
            instances.append(mod_name)
            seen.add(mod_name)

    return instances


def _topological_sort(
    modules: dict[str, VerilogModule],
) -> list[Path]:
    visited: set[str] = set()
    order: list[str] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        mod = modules.get(name)
        if mod:
            for inst in mod.instances:
                visit(inst)
            order.append(name)

    for name in modules:
        visit(name)

    seen_files: set[Path] = set()
    file_order: list[Path] = []
    for name in order:
        mod = modules.get(name)
        if mod and mod.file_path not in seen_files:
            file_order.append(mod.file_path)
            seen_files.add(mod.file_path)

    return file_order


def _find_top_module(
    modules: dict[str, VerilogModule],
) -> VerilogModule:
    all_names = set(modules.keys())
    instantiated: set[str] = set()
    for mod in modules.values():
        instantiated.update(mod.instances)

    top_candidates = all_names - instantiated

    tb_patterns = re.compile(r"(tb_|_tb$|test|bench|sim)", re.IGNORECASE)
    non_tb = [
        name for name in top_candidates
        if not tb_patterns.search(name)
    ]

    if len(non_tb) == 1:
        return modules[non_tb[0]]

    if len(non_tb) > 1:
        for preferred in ["top", "chip_top", "soc_top", "core_top"]:
            if preferred in non_tb:
                return modules[preferred]

        by_port_count = sorted(non_tb, key=lambda n: len(modules[n].ports), reverse=True)
        return modules[by_port_count[0]]

    if top_candidates:
        return modules[next(iter(top_candidates))]

    by_port_count = sorted(all_names, key=lambda n: len(modules[n].ports), reverse=True)
    return modules[by_port_count[0]]


def analyze_design(
    rtl_dir: Path,
    top_module_name: str | None = None,
) -> DesignAnalysis:
    hdl_files = discover_rtl_files(rtl_dir)
    if not hdl_files:
        raise FileNotFoundError(f"No HDL files found under {rtl_dir}")

    all_modules: dict[str, VerilogModule] = {}
    hdl_type = HDLType.VERILOG

    for f in hdl_files:
        ft = detect_hdl_type(f)
        if ft == HDLType.VHDL:
            hdl_type = HDLType.VHDL
        elif ft == HDLType.SYSTEMVERILOG:
            hdl_type = HDLType.SYSTEMVERILOG

        for mod in parse_hdl_file(f):
            all_modules[mod.name] = mod

    all_module_names = set(all_modules.keys())
    for f in hdl_files:
        if detect_hdl_type(f) == HDLType.VHDL:
            continue
        raw = f.read_text(encoding="utf-8", errors="ignore")
        clean = _strip_comments(raw)

        for mod in all_modules.values():
            if mod.file_path == f:
                mod.instances = _resolve_instances(clean, all_module_names)

    if top_module_name:
        if top_module_name not in all_modules:
            raise ValueError(
                f"Specified top module '{top_module_name}' not found. "
                f"Available: {sorted(all_modules.keys())}"
            )
        top = all_modules[top_module_name]
    else:
        top = _find_top_module(all_modules)

    clock_ports = [p for p in top.ports if p.is_clock]
    reset_ports = [p for p in top.ports if p.is_reset]

    file_order = _topological_sort(all_modules)

    for f in hdl_files:
        if f not in file_order:
            file_order.append(f)

    rtl_subdir = _detect_rtl_subdir(rtl_dir)

    return DesignAnalysis(
        top_module=top,
        all_modules=all_modules,
        clock_ports=clock_ports,
        reset_ports=reset_ports,
        file_order=file_order,
        rtl_dir_name=rtl_subdir,
        hdl_type=hdl_type,
    )
