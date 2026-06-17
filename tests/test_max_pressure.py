from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.controllers.max_pressure import MaxPressureController, _RegimeSnapshot


def snapshot(
    *,
    load: float,
    imbalance: float = 0.0,
    wait_imbalance: float = 0.0,
    burstiness: float = 0.0,
    platoon_score: float = 0.0,
    downstream_score: float = 0.0,
) -> _RegimeSnapshot:
    return _RegimeSnapshot(
        load=load,
        imbalance=imbalance,
        wait_imbalance=wait_imbalance,
        burstiness=burstiness,
        platoon_score=platoon_score,
        downstream_score=downstream_score,
    )


class MaxPressureSuperRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = MaxPressureController(
            super_router=True,
            super_low_load=0.38,
            super_program0_exit_load=0.28,
            super_high_load=0.62,
            super_nmin_load=0.72,
            super_imbalance_threshold=0.50,
            super_wait_imbalance_threshold=0.50,
            super_burstiness_threshold=0.10,
            super_platoon_threshold=0.50,
        )

    def test_program0_hysteresis_keeps_the_current_mp_branch(self) -> None:
        transitional_load = snapshot(load=0.33)

        self.assertEqual(
            self.controller._select_super_mode(transitional_load, "program0"),
            "program0",
        )
        self.assertEqual(
            self.controller._select_super_mode(transitional_load, "base"),
            "base",
        )
        self.assertEqual(
            self.controller._select_super_mode(snapshot(load=0.20), "base"),
            "program0",
        )

    def test_live_signals_select_the_expected_specialists(self) -> None:
        self.assertEqual(
            self.controller._select_super_mode(
                snapshot(load=0.50, wait_imbalance=0.60, imbalance=0.60),
                "base",
            ),
            "lta",
        )
        self.assertEqual(
            self.controller._select_super_mode(
                snapshot(load=0.50, platoon_score=1.0),
                "base",
            ),
            "platoon",
        )
        self.assertEqual(
            self.controller._select_super_mode(
                snapshot(load=0.75, burstiness=0.20),
                "base",
            ),
            "nmin",
        )

    def test_platoon_score_matches_the_standalone_headway_rule(self) -> None:
        traffic_light = SimpleNamespace(
            movements_by_phase={0: [("in_lane", "out_lane")]}
        )

        with patch.object(self.controller, "_lane_headway", return_value=2.0):
            self.assertEqual(
                self.controller._phase_platoon_score(traffic_light, 0, 10.0),
                1.0,
            )
        with patch.object(self.controller, "_lane_headway", return_value=2.2):
            self.assertEqual(
                self.controller._phase_platoon_score(traffic_light, 0, 10.0),
                0.0,
            )

    def test_safe_can_be_disabled_without_changing_other_rules(self) -> None:
        critical = snapshot(
            load=0.80,
            burstiness=0.20,
            downstream_score=1.0,
        )
        self.assertEqual(
            self.controller._select_super_mode(critical, "nmin"),
            "safe",
        )

        self.controller.super_safe_enabled = False
        self.assertEqual(
            self.controller._select_super_mode(critical, "nmin"),
            "nmin",
        )


if __name__ == "__main__":
    unittest.main()
