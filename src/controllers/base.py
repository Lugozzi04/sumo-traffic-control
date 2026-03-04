from abc import ABC, abstractmethod

import traci


class TrafficController(ABC):
    def __init__(self) -> None:
        self.traffic_lights: list[str] = []

    def attach_to_all_traffic_lights(self) -> None:
        self.traffic_lights = list(traci.trafficlight.getIDList())
        self.on_attach()

    def on_attach(self) -> None:
        # Hook opzionale per setup iniziale.
        return

    @abstractmethod
    def step(self) -> None:
        pass
