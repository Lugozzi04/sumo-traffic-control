from __future__ import annotations

import traci

from .base import TrafficController


class FixedTimeController(TrafficController):
    def __init__(
        self,
        *,
        program_id: str = "",
        main_green_seconds: float = 0.0,
        main_green_scale: float = 1.0,
    ) -> None:
        super().__init__()
        self.program_id = program_id.strip()
        self.main_green_seconds = float(main_green_seconds)
        self.main_green_scale = float(main_green_scale)

    @staticmethod
    def _is_main_green_state(state: str) -> bool:
        # Main green: contains green and no yellow transitions.
        return (("G" in state) or ("g" in state)) and ("y" not in state and "Y" not in state)

    @staticmethod
    def _logic_by_program_id(tls_id: str, program_id: str):
        for logic in traci.trafficlight.getAllProgramLogics(tls_id):
            if logic.programID == program_id:
                return logic
        return None

    def _build_tuned_logic(self, logic, current_phase_index: int):
        phases = []
        for phase in logic.phases:
            duration = float(phase.duration)
            if self._is_main_green_state(phase.state):
                if self.main_green_seconds > 0:
                    duration = self.main_green_seconds
                elif abs(self.main_green_scale - 1.0) > 1e-9:
                    duration = duration * self.main_green_scale
                duration = max(1.0, duration)

            phases.append(
                traci.trafficlight.Phase(
                    duration,
                    phase.state,
                    duration,
                    duration,
                    phase.next,
                    phase.name,
                )
            )

        return traci.trafficlight.Logic(
            logic.programID,
            logic.type,
            current_phase_index,
            phases,
            dict(logic.subParameter or {}),
        )

    def on_attach(self) -> None:
        for tls_id in self.traffic_lights:
            # Optional: force a specific existing static program (for fair fixed baselines).
            if self.program_id:
                if self._logic_by_program_id(tls_id, self.program_id) is not None:
                    traci.trafficlight.setProgram(tls_id, self.program_id)

            # Optional: tune only the main green durations while keeping transitions unchanged.
            if self.main_green_seconds > 0 or abs(self.main_green_scale - 1.0) > 1e-9:
                current_program_id = self.program_id or traci.trafficlight.getProgram(tls_id)
                logic = self._logic_by_program_id(tls_id, current_program_id)
                if logic is None:
                    continue
                current_phase_index = int(traci.trafficlight.getPhase(tls_id))
                tuned_logic = self._build_tuned_logic(logic, current_phase_index)
                traci.trafficlight.setProgramLogic(tls_id, tuned_logic)

    def step(self) -> None:
        # Nessuna azione online: SUMO usa il piano statico (eventualmente forzato/tuned in on_attach).
        return
