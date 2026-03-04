from .base import TrafficController


class FixedTimeController(TrafficController):
    def step(self) -> None:
        # Nessuna azione: SUMO usa i cicli statici definiti nella mappa.
        return
