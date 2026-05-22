from __future__ import annotations

import unittest

import argparse

from utils.run_ablation import (
    FIXED_PROGRAM0_SCENARIO,
    FIXED_TUNED_SCENARIO,
    SCENARIO_PACKS,
    Scenario,
    build_case_id,
    build_selected_scenarios,
    resolve_demand_preset,
    resolve_delta_baseline_scenario,
    resolve_population_preset,
    resolve_population_variants,
)


class RunAblationDemandTest(unittest.TestCase):
    def test_map_specific_overrides_remain_stable(self) -> None:
        masa_high = resolve_demand_preset("masa_100pc", "high")
        bologna_medium = resolve_demand_preset("bologna", "medium")

        self.assertEqual(masa_high.vehicles, 2700)
        self.assertEqual(bologna_medium.vehicles, 3000)

    def test_heuristic_preset_for_unmapped_network(self) -> None:
        preset = resolve_demand_preset("manhattan8x8_100pc", "medium")

        self.assertGreater(preset.vehicles, 0)
        self.assertLess(preset.vehicles, 7000)

    def test_population_presets_are_distinct(self) -> None:
        balanced = resolve_population_preset("balanced")
        skewed = resolve_population_preset("skewed")
        peak = resolve_population_preset("peak")

        self.assertEqual(balanced.route_sampling, "uniform")
        self.assertEqual(balanced.depart_profile, "uniform")
        self.assertEqual(skewed.route_sampling, "edge_weighted")
        self.assertEqual(skewed.depart_profile, "uniform")
        self.assertEqual(peak.route_sampling, "edge_weighted")
        self.assertEqual(peak.depart_profile, "peaked")
        self.assertGreater(peak.peak_factor, skewed.peak_factor)

    def test_case_id_includes_population_set_when_present(self) -> None:
        self.assertEqual(
            build_case_id("bologna", "low", 2, "mp_base", "skewed"),
            "bologna__skewed__low__seed2__mp_base",
        )

    def test_classic_baselines_skip_fixed_base(self) -> None:
        scenario_pack = (
            Scenario("mp_base", ()),
            Scenario("mp_lta_g040_sf050", ("--lost-time-aware",)),
        )
        args = argparse.Namespace(
            scenarios=[],
            include_classic_baselines=True,
            include_fixed_baseline=False,
            include_fixed_program0=False,
            include_fixed_tuned=False,
            include_rbl_baseline=False,
        )

        selected = build_selected_scenarios(
            scenario_pack,
            args.scenarios,
            args.include_classic_baselines,
            args.include_fixed_baseline,
            args.include_fixed_program0,
            args.include_fixed_tuned,
            args.include_rbl_baseline,
        )

        self.assertEqual([scenario.name for scenario in selected], ["mp_base", "mp_lta_g040_sf050", "fixed_program0", "fixed_tuned"])

    def test_tuning_matrix_v2_includes_program0_hybrid(self) -> None:
        names = [scenario.name for scenario in SCENARIO_PACKS["tuning_matrix_v2"]]
        self.assertIn("mp_program0", names)

    def test_default_delta_baseline_prefers_program0_then_tuned(self) -> None:
        scenarios = (Scenario("mp_base", ()), FIXED_TUNED_SCENARIO)
        self.assertEqual(resolve_delta_baseline_scenario(scenarios, ""), "fixed_tuned")
        scenarios = (Scenario("mp_base", ()), FIXED_PROGRAM0_SCENARIO, FIXED_TUNED_SCENARIO)
        self.assertEqual(resolve_delta_baseline_scenario(scenarios, ""), "fixed_program0")
        self.assertEqual(resolve_delta_baseline_scenario((Scenario("fixed_base", ()),), ""), "mp_base")
        self.assertEqual(resolve_delta_baseline_scenario(scenarios, "fixed_base"), "fixed_base")

    def test_legacy_spillback_name_maps_to_current_scenario(self) -> None:
        scenario_pack = (
            Scenario("mp_spillback_on85_off70", ("--spillback",)),
            Scenario("mp_spillback_on90_off80", ("--spillback",)),
        )
        selected = build_selected_scenarios(
            scenario_pack,
            ["mp_spillback_on97_off90"],
            False,
            False,
            False,
            False,
            False,
        )

        self.assertEqual([scenario.name for scenario in selected], ["mp_spillback_on90_off80"])

    def test_legacy_base_v2_name_maps_to_current_scenario(self) -> None:
        scenario_pack = (
            Scenario("mp_program0", ("--program0-hybrid",)),
        )
        selected = build_selected_scenarios(
            scenario_pack,
            ["mp_base_v2"],
            False,
            False,
            False,
            False,
            False,
        )

        self.assertEqual([scenario.name for scenario in selected], ["mp_program0"])

    def test_multiple_population_sets_override_custom_population_flags(self) -> None:
        args = argparse.Namespace(
            population_set=["skewed", "peak"],
            population_route_sampling="uniform",
            population_route_weight_exponent=1.0,
            population_depart_profile="uniform",
            population_peak_factor=0.5,
        )
        variants = resolve_population_variants(args)
        self.assertEqual([name for name, _ in variants], ["skewed", "peak"])
        self.assertEqual(variants[0][1].route_sampling, "edge_weighted")
        self.assertEqual(variants[1][1].depart_profile, "peaked")


if __name__ == "__main__":
    unittest.main()
