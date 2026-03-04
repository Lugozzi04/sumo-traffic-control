from dataclasses import dataclass
from pathlib import Path
import csv

import traci


@dataclass
class VehicleMetrics:
    total_distance: float = 0.0
    total_travel_time: float = 0.0
    total_waiting_time: float = 0.0
    mean_speed: float = 0.0
    total_co2: float = 0.0
    total_fuel: float = 0.0


class MetricsCollector:
    def __init__(self) -> None:
        self._data: dict[str, VehicleMetrics] = {}

    def capture_step(self, active_vehicle_ids: set[str], delta_t_ms: float) -> None:
        for vehicle_id in active_vehicle_ids:
            metrics = self._data.setdefault(vehicle_id, VehicleMetrics())

            metrics.total_distance = traci.vehicle.getDistance(vehicle_id)
            metrics.total_waiting_time = traci.vehicle.getAccumulatedWaitingTime(vehicle_id)
            metrics.total_travel_time = traci.simulation.getTime() - traci.vehicle.getDeparture(vehicle_id)

            if metrics.total_travel_time > 0:
                metrics.mean_speed = metrics.total_distance / metrics.total_travel_time

            # Emissioni e consumi in g per step (delta_t in secondi, TraCI ritorna mg/s).
            metrics.total_co2 += (traci.vehicle.getCO2Emission(vehicle_id) * delta_t_ms) / 1000.0
            metrics.total_fuel += (traci.vehicle.getFuelConsumption(vehicle_id) * delta_t_ms) / 1000.0

    def snapshot(self) -> dict[str, VehicleMetrics]:
        return self._data


def aggregate_runs(runs: list[dict[str, VehicleMetrics]]) -> dict[str, VehicleMetrics]:
    sums: dict[str, VehicleMetrics] = {}
    counts: dict[str, int] = {}

    for run in runs:
        for vehicle_id, metrics in run.items():
            if vehicle_id not in sums:
                sums[vehicle_id] = VehicleMetrics()
                counts[vehicle_id] = 0

            counts[vehicle_id] += 1
            sums[vehicle_id].total_distance += metrics.total_distance
            sums[vehicle_id].total_travel_time += metrics.total_travel_time
            sums[vehicle_id].total_waiting_time += metrics.total_waiting_time
            sums[vehicle_id].mean_speed += metrics.mean_speed
            sums[vehicle_id].total_co2 += metrics.total_co2
            sums[vehicle_id].total_fuel += metrics.total_fuel

    averaged: dict[str, VehicleMetrics] = {}
    for vehicle_id, metrics in sums.items():
        count = counts[vehicle_id]
        averaged[vehicle_id] = VehicleMetrics(
            total_distance=metrics.total_distance / count,
            total_travel_time=metrics.total_travel_time / count,
            total_waiting_time=metrics.total_waiting_time / count,
            mean_speed=metrics.mean_speed / count,
            total_co2=metrics.total_co2 / count,
            total_fuel=metrics.total_fuel / count,
        )

    return averaged


def write_metrics_csv(filename: Path, metrics: dict[str, VehicleMetrics]) -> None:
    with filename.open("w", newline="", encoding="utf-8") as fd:
        writer = csv.writer(fd, delimiter=";")
        writer.writerow(
            [
                "vehicle_id",
                "distance_m",
                "travel_time_s",
                "waiting_time_s",
                "mean_speed_mps",
                "co2_g",
                "fuel_g",
            ]
        )

        for vehicle_id, values in sorted(metrics.items()):
            writer.writerow(
                [
                    vehicle_id,
                    values.total_distance,
                    values.total_travel_time,
                    values.total_waiting_time,
                    values.mean_speed,
                    values.total_co2,
                    values.total_fuel,
                ]
            )
