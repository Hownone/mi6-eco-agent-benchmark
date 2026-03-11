from __future__ import annotations

import json

from benchmark.config import BenchmarkConfig
from benchmark.models import DesignAnalysis


def generate_design_json(
    analysis: DesignAnalysis,
    config: BenchmarkConfig,
) -> str:
    data = {
        "design": analysis.top_module.name,
        "netlist": "data/signoff.v",
        "def": "data/signoff.def",
        "constraint_modes": [
            {
                "name": "func",
                "sdc_files": ["data/signoff.sdc"],
            }
        ],
        "max_route_layer": config.default_max_route_layer,
        "min_route_layer": config.default_min_route_layer,
        "power_nets": config.default_power_nets,
        "ground_nets": config.default_ground_nets,
    }

    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
