from dataclasses import dataclass
from typing import Optional

import traci

from .base import TrafficController


@dataclass
class _TrafficLightData:
    phase_count: int
    main_phases: list[int]
    movements_by_phase: dict[int, list[tuple[str, str]]]
    pending_target: Optional[int] = None


class MaxPressureController(TrafficController):
    """
    MVP Max-Pressure controller.

    Pressure for a phase is the sum of (upstream queue - downstream queue)
    over all lane->lane movements with green in that phase.
    """

    def __init__(self, min_green: float = 10.0, max_green: float = 120.0, switch_epsilon: float = 0.0) -> None:
        super().__init__()
        self.min_green = min_green
        self.max_green = max_green
        self.switch_epsilon = switch_epsilon
        self._data: dict[str, _TrafficLightData] = {}

    def on_attach(self) -> None:
        for tl_id in self.traffic_lights:
            logics = traci.trafficlight.getAllProgramLogics(tl_id)
            if not logics:
                continue

            # If available, use program 1 as dynamic baseline; otherwise fallback to the only logic.
            logic = logics[1] if len(logics) > 1 else logics[0]
            traci.trafficlight.setProgram(tl_id, logic.programID)

            tl_data = self._build_traffic_light_data(tl_id, logic)
            if tl_data.main_phases:
                self._data[tl_id] = tl_data

    def _build_traffic_light_data(self, tl_id: str, logic) -> _TrafficLightData:
        controlled_links = traci.trafficlight.getControlledLinks(tl_id)
        movements_by_phase: dict[int, list[tuple[str, str]]] = {}

        for phase_index, phase in enumerate(logic.phases):
            if not self._is_main_phase_state(phase.state):
                continue

            seen_movements: set[tuple[str, str]] = set()
            movements: list[tuple[str, str]] = []

            for signal_index, signal_state in enumerate(phase.state):
                if signal_state not in ("g", "G"):
                    continue
                if signal_index >= len(controlled_links):
                    continue

                link_group = controlled_links[signal_index]
                if not link_group:
                    continue

                for in_lane, out_lane, _ in link_group:
                    movement = (in_lane, out_lane)
                    if movement in seen_movements:
                        continue
                    seen_movements.add(movement)
                    movements.append(movement)

            if movements:
                movements_by_phase[phase_index] = movements

        return _TrafficLightData(
            phase_count=len(logic.phases),
            main_phases=sorted(movements_by_phase.keys()),
            movements_by_phase=movements_by_phase,
        )

    @staticmethod
    def _is_main_phase_state(state: str) -> bool:
        # Main phases contain green and no yellow symbols.
        return any(char in ("g", "G") for char in state) and not any(char in ("y", "Y") for char in state)

    @staticmethod
    def _is_phase_ending(tl_id: str) -> bool:
        spent = traci.trafficlight.getSpentDuration(tl_id)
        duration = traci.trafficlight.getPhaseDuration(tl_id)
        return spent >= duration - 1e-6

    def _phase_pressures(self, tl_data: _TrafficLightData) -> dict[int, float]:
        lane_queue_cache: dict[str, float] = {}

        def queue_on_lane(lane_id: str) -> float:
            if lane_id not in lane_queue_cache:
                lane_queue_cache[lane_id] = float(traci.lane.getLastStepHaltingNumber(lane_id))
            return lane_queue_cache[lane_id]

        pressures: dict[int, float] = {}
        for phase_index, movements in tl_data.movements_by_phase.items():
            pressure = 0.0
            for in_lane, out_lane in movements:
                pressure += queue_on_lane(in_lane) - queue_on_lane(out_lane)
            pressures[phase_index] = pressure
        return pressures

    @staticmethod
    def _advance_to_next_phase(tl_id: str, phase_count: int) -> None:
        current_phase = traci.trafficlight.getPhase(tl_id)
        traci.trafficlight.setPhase(tl_id, (current_phase + 1) % phase_count)

    def _handle_pending_target(self, tl_id: str, tl_data: _TrafficLightData) -> None:
        target_phase = tl_data.pending_target
        if target_phase is None:
            return

        current_phase = traci.trafficlight.getPhase(tl_id)

        if current_phase == target_phase and current_phase in tl_data.main_phases:
            tl_data.pending_target = None
            return

        # If we are unexpectedly in a different main phase, jump to the selected target.
        if current_phase in tl_data.main_phases and current_phase != target_phase:
            traci.trafficlight.setPhase(tl_id, target_phase)
            tl_data.pending_target = None
            return

        # During transition phases, wait for phase end to preserve yellow/all-red timing.
        if not self._is_phase_ending(tl_id):
            return

        next_phase = (current_phase + 1) % tl_data.phase_count
        if next_phase in tl_data.main_phases:
            if next_phase != target_phase:
                traci.trafficlight.setPhase(tl_id, target_phase)
            tl_data.pending_target = None

    def step(self) -> None:
        for tl_id in self.traffic_lights:
            tl_data = self._data.get(tl_id)
            if tl_data is None:
                continue

            if tl_data.pending_target is not None:
                self._handle_pending_target(tl_id, tl_data)
                continue

            current_phase = traci.trafficlight.getPhase(tl_id)
            if current_phase not in tl_data.main_phases:
                continue

            spent = traci.trafficlight.getSpentDuration(tl_id)
            if spent < self.min_green:
                continue

            pressures = self._phase_pressures(tl_data)
            if current_phase not in pressures or len(pressures) <= 1:
                continue

            best_phase, best_pressure = max(pressures.items(), key=lambda item: item[1])
            current_pressure = pressures[current_phase]

            if best_phase != current_phase and best_pressure > current_pressure + self.switch_epsilon:
                tl_data.pending_target = best_phase
                self._advance_to_next_phase(tl_id, tl_data.phase_count)
                continue

            # Safety cap to avoid overextending one phase in pathological cases.
            if spent >= self.max_green and best_phase != current_phase:
                tl_data.pending_target = best_phase
                self._advance_to_next_phase(tl_id, tl_data.phase_count)
