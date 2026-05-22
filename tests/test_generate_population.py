from __future__ import annotations

import unittest

from generate_population import RouteInfo, build_population


class GeneratePopulationTest(unittest.TestCase):
    def test_departures_are_sorted_and_stay_in_window(self) -> None:
        route_infos = [RouteInfo(route_id="r1", edge_count=2), RouteInfo(route_id="r2", edge_count=5)]
        population = build_population(
            route_infos=route_infos,
            n_vehicles=20,
            start_time=10.0,
            end_time=20.0,
            seed=7,
            route_sampling="uniform",
            route_weight_exponent=1.0,
            depart_profile="peaked",
            peak_factor=0.8,
        )

        departs = [vehicle["depart"] for vehicle in population]
        self.assertEqual(departs, sorted(departs))
        self.assertGreaterEqual(min(departs), 10.0)
        self.assertLessEqual(max(departs), 20.0)

    def test_edge_weighted_prefers_longer_routes(self) -> None:
        route_infos = [RouteInfo(route_id="short", edge_count=1), RouteInfo(route_id="long", edge_count=10)]
        population = build_population(
            route_infos=route_infos,
            n_vehicles=200,
            start_time=0.0,
            end_time=60.0,
            seed=13,
            route_sampling="edge_weighted",
            route_weight_exponent=2.0,
            depart_profile="uniform",
            peak_factor=0.75,
        )

        route_counts = {route_id: 0 for route_id in ("short", "long")}
        for vehicle in population:
            route_counts[vehicle["route_id"]] += 1

        self.assertGreater(route_counts["long"], route_counts["short"])


if __name__ == "__main__":
    unittest.main()
