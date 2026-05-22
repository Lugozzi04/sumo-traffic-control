from dataclasses import dataclass
from pathlib import Path
import csv
import xml.etree.ElementTree as ET

import traci


@dataclass
class VehicleMetrics:
    total_distance: float = 0.0
    total_travel_time: float = 0.0
    total_waiting_time: float = 0.0
    time_loss_s: float = 0.0
    mean_speed: float = 0.0
    total_co2: float = 0.0
    total_fuel: float = 0.0


def _safe_mean(values: list[float]) -> float:
    return sum(values) / float(len(values)) if values else 0.0


def _parse_tripinfo_file(filename: Path) -> dict[str, VehicleMetrics]:
    if not filename.exists():
        raise FileNotFoundError(f"Tripinfo file non trovato: {filename}")

    root = ET.parse(filename).getroot()
    metrics: dict[str, VehicleMetrics] = {}
    for tripinfo in root.findall("tripinfo"):
        vehicle_id = tripinfo.get("id")
        if not vehicle_id:
            continue

        total_distance = float(tripinfo.get("routeLength", "0.0"))
        total_travel_time = float(tripinfo.get("duration", "0.0"))
        total_waiting_time = float(tripinfo.get("waitingTime", "0.0"))
        time_loss_s = float(tripinfo.get("timeLoss", "0.0"))
        mean_speed = total_distance / total_travel_time if total_travel_time > 0 else 0.0

        metrics[vehicle_id] = VehicleMetrics(
            total_distance=total_distance,
            total_travel_time=total_travel_time,
            total_waiting_time=total_waiting_time,
            time_loss_s=time_loss_s,
            mean_speed=mean_speed,
        )

    return metrics


def summarize_trip_metrics(metrics: dict[str, VehicleMetrics], planned_vehicle_count: int) -> dict[str, float]:
    completed_trips = len(metrics)
    unfinished_trips = max(0, planned_vehicle_count - completed_trips)
    planned_trips = max(0, planned_vehicle_count)
    censoring_rate = unfinished_trips / float(planned_trips) if planned_trips > 0 else 0.0

    values = list(metrics.values())
    return {
        "planned_trips": float(planned_trips),
        "completed_trips": float(completed_trips),
        "unfinished_trips": float(unfinished_trips),
        "censoring_rate": float(censoring_rate),
        "mean_distance_m": _safe_mean([item.total_distance for item in values]),
        "mean_travel_time_s": _safe_mean([item.total_travel_time for item in values]),
        "mean_waiting_time_s": _safe_mean([item.total_waiting_time for item in values]),
        "mean_time_loss_s": _safe_mean([item.time_loss_s for item in values]),
        "mean_speed_mps": _safe_mean([item.mean_speed for item in values]),
        "mean_co2_g": _safe_mean([item.total_co2 for item in values]),
        "mean_fuel_g": _safe_mean([item.total_fuel for item in values]),
    }


class MetricsCollector:
    def __init__(self) -> None:
        self._data: dict[str, VehicleMetrics] = {}

    def capture_step(self, active_vehicle_ids: set[str], delta_t_ms: float) -> None:
        for vehicle_id in active_vehicle_ids:
            metrics = self._data.setdefault(vehicle_id, VehicleMetrics())

            # Emissioni e consumi in g per step (delta_t in secondi, TraCI ritorna mg/s).
            metrics.total_co2 += (traci.vehicle.getCO2Emission(vehicle_id) * delta_t_ms) / 1000.0
            metrics.total_fuel += (traci.vehicle.getFuelConsumption(vehicle_id) * delta_t_ms) / 1000.0

    def finalize_tripinfo(self, tripinfo_file: Path, planned_vehicle_ids: set[str]) -> dict[str, float]:
        trip_metrics = _parse_tripinfo_file(tripinfo_file)

        for vehicle_id, metrics in trip_metrics.items():
            cached = self._data.get(vehicle_id)
            if cached is not None:
                metrics.total_co2 = cached.total_co2
                metrics.total_fuel = cached.total_fuel

        self._data = trip_metrics
        return summarize_trip_metrics(trip_metrics, len(planned_vehicle_ids))

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
            sums[vehicle_id].time_loss_s += metrics.time_loss_s
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
            time_loss_s=metrics.time_loss_s / count,
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
                "time_loss_s",
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
                    values.time_loss_s,
                    values.mean_speed,
                    values.total_co2,
                    values.total_fuel,
                ]
            )
