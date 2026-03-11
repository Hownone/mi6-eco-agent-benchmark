from __future__ import annotations

import logging
import shutil
from pathlib import Path

from benchmark.config import BenchmarkConfig
from benchmark.generators.design_json_gen import generate_design_json
from benchmark.generators.flist_gen import generate_flist
from benchmark.generators.load_tcl_gen import generate_load_tcl
from benchmark.generators.sdc_gen import generate_sdc
from benchmark.models import DesignAnalysis
from benchmark.rtl_analyzer.hierarchy import analyze_design

logger = logging.getLogger(__name__)


async def build_case(
    rtl_source_dir: Path,
    output_dir: Path,
    config: BenchmarkConfig,
    top_module: str | None = None,
    clock_period: float | None = None,
    copy_rtl: bool = True,
) -> DesignAnalysis:
    rtl_source_dir = rtl_source_dir.resolve()
    output_dir = output_dir.resolve()

    if not rtl_source_dir.exists():
        raise FileNotFoundError(f"RTL source directory not found: {rtl_source_dir}")

    logger.info("Analyzing RTL in %s", rtl_source_dir)
    analysis = analyze_design(rtl_source_dir, top_module)
    logger.info(
        "Design: top=%s, modules=%d, clocks=%d, resets=%d, files=%d",
        analysis.top_module.name,
        len(analysis.all_modules),
        len(analysis.clock_ports),
        len(analysis.reset_ports),
        len(analysis.file_order),
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    rtl_out = output_dir / "rtl"
    if copy_rtl:
        if rtl_out.exists():
            shutil.rmtree(rtl_out)
        rtl_out.mkdir(parents=True, exist_ok=True)

        for f in analysis.file_order:
            dest = rtl_out / f.name
            shutil.copy2(f, dest)
        logger.info("Copied %d RTL files to %s", len(analysis.file_order), rtl_out)

    patched_analysis = DesignAnalysis(
        top_module=analysis.top_module,
        all_modules=analysis.all_modules,
        clock_ports=analysis.clock_ports,
        reset_ports=analysis.reset_ports,
        file_order=analysis.file_order,
        rtl_dir_name="rtl",
        hdl_type=analysis.hdl_type,
    )

    logger.info("Generating func.sdc via LLM...")
    sdc_content = await generate_sdc(patched_analysis, config, clock_period)
    (output_dir / "func.sdc").write_text(sdc_content, encoding="utf-8")
    logger.info("Written func.sdc (%d bytes)", len(sdc_content))

    load_tcl_content = generate_load_tcl(patched_analysis)
    (output_dir / "load.tcl").write_text(load_tcl_content, encoding="utf-8")
    logger.info("Written load.tcl")

    flist_content = generate_flist(patched_analysis)
    (output_dir / "mi6.flist").write_text(flist_content, encoding="utf-8")
    logger.info("Written mi6.flist")

    design_dir = output_dir / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    (design_dir / "data").mkdir(parents=True, exist_ok=True)

    design_json_content = generate_design_json(patched_analysis, config)
    (design_dir / "design.json").write_text(design_json_content, encoding="utf-8")
    logger.info("Written design/design.json")

    logger.info("Case built successfully at %s", output_dir)
    return analysis
