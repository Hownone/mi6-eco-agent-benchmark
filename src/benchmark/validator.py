from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    case_dir: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def validate_case(case_dir: Path, require_signoff: bool = False) -> ValidationResult:
    result = ValidationResult(case_dir=case_dir)

    if not case_dir.exists():
        result.errors.append(f"Case directory does not exist: {case_dir}")
        return result

    rtl_dir = case_dir / "rtl"
    if not rtl_dir.exists():
        result.errors.append("Missing rtl/ directory")
    else:
        rtl_files = list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.vhd"))
        if not rtl_files:
            result.errors.append("No HDL files found in rtl/")

    for required_file in ["func.sdc", "load.tcl", "mi6.flist"]:
        p = case_dir / required_file
        if not p.exists():
            result.errors.append(f"Missing {required_file}")
        elif p.stat().st_size == 0:
            result.errors.append(f"{required_file} is empty")

    design_json = case_dir / "design" / "design.json"
    if not design_json.exists():
        result.errors.append("Missing design/design.json")
    else:
        try:
            data = json.loads(design_json.read_text(encoding="utf-8"))
            if "design" not in data:
                result.errors.append("design.json missing 'design' field")
            if "netlist" not in data:
                result.errors.append("design.json missing 'netlist' field")
            if "def" not in data:
                result.errors.append("design.json missing 'def' field")
        except json.JSONDecodeError as e:
            result.errors.append(f"design.json is not valid JSON: {e}")

    sdc_file = case_dir / "func.sdc"
    if sdc_file.exists():
        sdc_text = sdc_file.read_text(encoding="utf-8")
        if "create_clock" not in sdc_text:
            result.warnings.append("func.sdc does not contain create_clock command")

    load_tcl = case_dir / "load.tcl"
    if load_tcl.exists():
        tcl_text = load_tcl.read_text(encoding="utf-8")
        if "read_hdl" not in tcl_text:
            result.warnings.append("load.tcl does not contain read_hdl command")

    if require_signoff:
        data_dir = case_dir / "design" / "data"
        for signoff_file in ["signoff.v", "signoff.def", "signoff.sdc"]:
            p = data_dir / signoff_file
            if not p.exists():
                result.errors.append(f"Missing design/data/{signoff_file} (signoff required)")

    if not (case_dir / "design" / "data").exists():
        result.warnings.append("design/data/ directory does not exist (no signoff data)")

    return result
