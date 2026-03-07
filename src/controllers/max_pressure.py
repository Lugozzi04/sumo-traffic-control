from dataclasses import dataclass
from typing import Optional

import traci

from .base import TrafficController


@dataclass
class _TrafficLightData:
    phase_count: int
    phase_durations: list[float]
    main_phases: list[int]
    movements_by_phase: dict[int, list[tuple[str, str]]]
    wait_time_by_phase: dict[int, float]
    active_phase: Optional[int] = None
    active_hold_seconds: float = 0.0
    active_empty_seconds: float = 0.0
    pending_target: Optional[int] = None


class MaxPressureController(TrafficController):
    """
    MVP Max-Pressure controller.

    Pressure for a phase is the sum of (upstream queue - downstream queue)
    over all lane->lane movements with green in that phase.
    Optional hard spillback excludes movements whose downstream lane is near saturation.
    """

    DEFAULT_SPILLBACK_ON = 0.90
    DEFAULT_SPILLBACK_OFF = 0.75
    DEFAULT_SPILLBACK_MIN_HALTS = 1
    DEFAULT_SPILLBACK_ALPHA = 0.5

    def __init__(
        self,
        min_green: float = 10.0,
        max_green: float = 120.0,
        switch_epsilon: float = 0.0,
        lost_time_aware: bool = False,
        lost_time_sat_flow: float = 0.5,
        lost_time_gain: float = 1.0,
        fairness: bool = False,
        fairness_mu: float = 5.0,
        fairness_w_half: float = 30.0,
        nmin_dynamic: bool = False,
        nmin_alpha: float = 1.0,
        nmin_floor: int = 2,
        nmin_empty_release_seconds: float = 2.0,
        hard_spillback: bool = False,
        spillback_on: float = DEFAULT_SPILLBACK_ON,
        spillback_off: float = DEFAULT_SPILLBACK_OFF,
        spillback_min_halts: int = DEFAULT_SPILLBACK_MIN_HALTS,
        spillback_alpha: float = DEFAULT_SPILLBACK_ALPHA,
    ) -> None:
        super().__init__()
        self.min_green = min_green
        self.max_green = max_green
        self.switch_epsilon = switch_epsilon
        self.lost_time_aware = lost_time_aware
        self.lost_time_sat_flow = lost_time_sat_flow
        self.lost_time_gain = lost_time_gain
        self.fairness = fairness
        self.fairness_mu = fairness_mu
        self.fairness_w_half = fairness_w_half
        self.nmin_dynamic = nmin_dynamic
        self.nmin_alpha = nmin_alpha
        self.nmin_floor = nmin_floor
        self.nmin_empty_release_seconds = nmin_empty_release_seconds
        self.hard_spillback = hard_spillback
        self.spillback_on = spillback_on
        self.spillback_off = spillback_off
        self.spillback_min_halts = spillback_min_halts
        self.spillback_alpha = spillback_alpha
        self._data: dict[str, _TrafficLightData] = {}
        self._downstream_occ_ema: dict[str, float] = {}
        self._downstream_blocked: dict[str, bool] = {}

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

        main_phases = sorted(movements_by_phase.keys())
        return _TrafficLightData(
            phase_count=len(logic.phases),
            phase_durations=[float(phase.duration) for phase in logic.phases],
            main_phases=main_phases,
            movements_by_phase=movements_by_phase,
            wait_time_by_phase={phase: 0.0 for phase in main_phases},
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

    @staticmethod
    def _lost_time_seconds(tl_data: _TrafficLightData, current_phase: int) -> float:
        # Lost time is the transition block (yellow/all-red) after leaving current main phase.
        lost_time = 0.0
        phase_idx = (current_phase + 1) % tl_data.phase_count
        for _ in range(tl_data.phase_count):
            if phase_idx in tl_data.main_phases:
                break
            lost_time += tl_data.phase_durations[phase_idx]
            phase_idx = (phase_idx + 1) % tl_data.phase_count
        return lost_time

    def _switch_margin(self, tl_data: _TrafficLightData, current_phase: int) -> float:
        margin = self.switch_epsilon
        if not self.lost_time_aware:
            return margin

        lost_time = self._lost_time_seconds(tl_data, current_phase)
        return margin + self.lost_time_gain * self.lost_time_sat_flow * lost_time

    @staticmethod
    def _delta_seconds() -> float:
        delta_t = float(traci.simulation.getDeltaT())
        return delta_t / 1000.0 if delta_t > 10.0 else delta_t

    def _downstream_occupancy(self, lane_id: str) -> float:
        raw_occ = float(traci.lane.getLastStepOccupancy(lane_id)) / 100.0
        previous = self._downstream_occ_ema.get(lane_id)
        if previous is None:
            ema = raw_occ
        else:
            ema = self.spillback_alpha * raw_occ + (1.0 - self.spillback_alpha) * previous
        self._downstream_occ_ema[lane_id] = ema
        return ema

    def _is_downstream_blocked(self, out_lane: str) -> bool:
        if not self.hard_spillback:
            return False

        occ = self._downstream_occupancy(out_lane)
        halts = int(traci.lane.getLastStepHaltingNumber(out_lane))
        blocked = self._downstream_blocked.get(out_lane, False)

        if blocked:
            # Hysteresis release: keep blocked until occupancy goes below the "off" threshold.
            blocked = occ >= self.spillback_off
        else:
            blocked = occ >= self.spillback_on and halts >= self.spillback_min_halts

        self._downstream_blocked[out_lane] = blocked
        return blocked

    def _phase_pressures(self, tl_data: _TrafficLightData) -> tuple[dict[int, float], dict[int, float]]:
        lane_queue_cache: dict[str, float] = {}
        downstream_blocked_cache: dict[str, bool] = {}

        def queue_on_lane(lane_id: str) -> float:
            if lane_id not in lane_queue_cache:
                lane_queue_cache[lane_id] = float(traci.lane.getLastStepHaltingNumber(lane_id))
            return lane_queue_cache[lane_id]

        def downstream_blocked(lane_id: str) -> bool:
            if lane_id not in downstream_blocked_cache:
                downstream_blocked_cache[lane_id] = self._is_downstream_blocked(lane_id)
            return downstream_blocked_cache[lane_id]

        pressures: dict[int, float] = {}
        phase_demand: dict[int, float] = {}
        for phase_index, movements in tl_data.movements_by_phase.items():
            pressure = 0.0
            available_movements = 0
            phase_blocked = False
            demand_sum = 0.0
            for in_lane, out_lane in movements:
                if downstream_blocked(out_lane):
                    # Hard constraint at phase level: if one movement spills back, skip the whole phase.
                    phase_blocked = True
                    break
                in_queue = queue_on_lane(in_lane)
                out_queue = queue_on_lane(out_lane)
                demand_sum += in_queue
                pressure += in_queue - out_queue
                available_movements += 1
            if phase_blocked or available_movements == 0:
                pressures[phase_index] = float("-inf")
                phase_demand[phase_index] = 0.0
            else:
                pressures[phase_index] = pressure
                phase_demand[phase_index] = demand_sum
        return pressures, phase_demand

    def _update_wait_times(self, tl_data: _TrafficLightData, current_phase: int, phase_demand: dict[int, float]) -> None:
        if not self.fairness:
            return

        delta_seconds = self._delta_seconds()
        for phase in tl_data.main_phases:
            if phase == current_phase:
                tl_data.wait_time_by_phase[phase] = 0.0
                continue
            if phase_demand.get(phase, 0.0) > 0.0:
                tl_data.wait_time_by_phase[phase] = tl_data.wait_time_by_phase.get(phase, 0.0) + delta_seconds
            else:
                tl_data.wait_time_by_phase[phase] = 0.0

    def _fairness_bonus(self, wait_seconds: float) -> float:
        if not self.fairness:
            return 0.0
        if self.fairness_w_half <= 0.0:
            return self.fairness_mu
        return self.fairness_mu * (wait_seconds / (wait_seconds + self.fairness_w_half))

    def _phase_scores(self, tl_data: _TrafficLightData, pressures: dict[int, float]) -> dict[int, float]:
        scores: dict[int, float] = {}
        for phase, pressure in pressures.items():
            if pressure == float("-inf"):
                scores[phase] = pressure
                continue
            bonus = self._fairness_bonus(tl_data.wait_time_by_phase.get(phase, 0.0))
            scores[phase] = pressure + bonus
        return scores

    def _nmin_hold_seconds(self, tl_data: _TrafficLightData, current_phase: int, phase_demand: dict[int, float]) -> float:
        if not self.nmin_dynamic:
            return self.min_green

        if self.lost_time_sat_flow <= 1e-6:
            return self.min_green

        lost_time = self._lost_time_seconds(tl_data, current_phase)
        n_cost = self.nmin_alpha * self.lost_time_sat_flow * lost_time
        n_target = max(float(self.nmin_floor), n_cost)

        # If current demand is small, avoid overholding a phase that is already almost drained.
        demand = max(0.0, phase_demand.get(current_phase, 0.0))
        if demand > 0.0:
            n_target = min(n_target, demand)

        service_seconds = n_target / self.lost_time_sat_flow
        return max(self.min_green, service_seconds)

    def _refresh_active_phase_state(self, tl_data: _TrafficLightData, current_phase: int, phase_demand: dict[int, float]) -> None:
        if tl_data.active_phase == current_phase:
            return
        tl_data.active_phase = current_phase
        tl_data.active_empty_seconds = 0.0
        tl_data.active_hold_seconds = self._nmin_hold_seconds(tl_data, current_phase, phase_demand)

    def _must_hold_current_phase(
        self,
        tl_data: _TrafficLightData,
        current_phase: int,
        spent: float,
        phase_demand: dict[int, float],
    ) -> bool:
        if not self.nmin_dynamic:
            return False
        if tl_data.active_phase != current_phase:
            return False
        if spent >= tl_data.active_hold_seconds:
            return False

        if phase_demand.get(current_phase, 0.0) > 0.0:
            tl_data.active_empty_seconds = 0.0
            return True

        tl_data.active_empty_seconds += self._delta_seconds()
        return tl_data.active_empty_seconds < self.nmin_empty_release_seconds

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

            pressures, phase_demand = self._phase_pressures(tl_data)
            self._update_wait_times(tl_data, current_phase, phase_demand)
            self._refresh_active_phase_state(tl_data, current_phase, phase_demand)

            spent = traci.trafficlight.getSpentDuration(tl_id)
            if spent < self.min_green:
                continue
            if self._must_hold_current_phase(tl_data, current_phase, spent, phase_demand):
                continue

            if current_phase not in pressures or len(pressures) <= 1:
                continue
            if all(value == float("-inf") for value in pressures.values()):
                continue

            scores = self._phase_scores(tl_data, pressures)
            best_phase, best_score = max(scores.items(), key=lambda item: item[1])
            current_score = scores[current_phase]
            switch_margin = self._switch_margin(tl_data, current_phase)

            if best_phase != current_phase and best_score > current_score + switch_margin:
                tl_data.pending_target = best_phase
                self._advance_to_next_phase(tl_id, tl_data.phase_count)
                continue

            # Safety cap to avoid overextending one phase in pathological cases.
            if spent >= self.max_green and best_phase != current_phase and best_score > float("-inf"):
                tl_data.pending_target = best_phase
                self._advance_to_next_phase(tl_id, tl_data.phase_count)
