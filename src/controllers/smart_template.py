import traci

from .base import TrafficController


class SmartTemplateController(TrafficController):
    def __init__(self, min_green: float = 10.0, max_green: float = 60.0) -> None:
        super().__init__()
        self.min_green = min_green
        self.max_green = max_green

    def on_attach(self) -> None:
        for tl_id in self.traffic_lights:
            # Se presente, usa il programID 1 come base per il controllo dinamico.
            if len(traci.trafficlight.getAllProgramLogics(tl_id)) > 1:
                traci.trafficlight.setProgram(tl_id, "1")
            else:
                traci.trafficlight.setProgram(tl_id, "0")

    def _is_green_phase(self, tl_id: str) -> bool:
        state = traci.trafficlight.getRedYellowGreenState(tl_id)
        return any(char in ("g", "G") for char in state)

    def _switch_to_next_phase(self, tl_id: str) -> None:
        current_phase = traci.trafficlight.getPhase(tl_id)
        next_phase = current_phase + 1
        traci.trafficlight.setPhase(tl_id, next_phase)

    def step(self) -> None:
        for tl_id in self.traffic_lights:
            spent = traci.trafficlight.getSpentDuration(tl_id)

            if not self._is_green_phase(tl_id):
                continue

            if spent < self.min_green:
                continue

            # TODO: Sostituisci questa regola con la tua strategia.
            # Qui facciamo solo una protezione semplice sul tempo massimo di verde.
            if spent >= self.max_green:
                self._switch_to_next_phase(tl_id)
