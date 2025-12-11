# traffic_manager.py

import random
import time
import pygame
from vehicle import Vehicle
import config

class TrafficManager:
    """
    Manages the core logic of the traffic simulation, including traffic light control,
    vehicle generation, and vehicle movement.
    """
    def __init__(self, vehicle_counts):
        """
        Initializes the TrafficManager.

        Args:
            vehicle_counts (dict): A dictionary with the number of vehicles for each lane.
        """
        self.vehicle_counts = vehicle_counts
        self.lanes = {"right": [], "left": [], "down": [], "up": []}
        
        # Simulation state variables
        self.current_green_lane_index = 0
        self.signal_lanes_order = ['right', 'down', 'left', 'up']
        self.current_signal_color = "red"
        self.last_signal_change_time = time.time()
        
        # Calculate dynamic green signal times based on vehicle counts
        self.green_signal_times = self._calculate_green_times()
        
        # Initialize vehicle sprites
        self._initialize_vehicles()

    def _calculate_green_times(self):
        """
        Calculates the duration of the green signal for each lane based on traffic density.
        The duration is proportional to the number of vehicles, with a minimum base time.
        """
        total_vehicles = sum(self.vehicle_counts.values())
        green_times = {}

        if total_vehicles == 0:
            # If no vehicles are detected, assign a default base time to all lanes
            for lane in self.signal_lanes_order:
                green_times[lane] = config.GREEN_SIGNAL_BASE_TIME
        else:
            # Distribute time proportionally
            for lane in self.signal_lanes_order:
                proportion = self.vehicle_counts.get(lane, 0) / total_vehicles
                # Time is base time + proportional extra time (scaled)
                additional_time = proportion * config.GREEN_SIGNAL_BASE_TIME
                green_times[lane] = int(config.GREEN_SIGNAL_BASE_TIME + additional_time)
        
        print("Calculated Green Signal Times (ms):", green_times)
        return green_times

    def _initialize_vehicles(self):
        """
        Creates and populates the vehicle sprites for each lane based on the counts.
        """
        for lane_direction, count in self.vehicle_counts.items():
            for _ in range(count):
                self.lanes[lane_direction].append(Vehicle(lane_direction))

    def update(self):
        """
        Updates the state of the simulation on each frame, including signal changes
        and vehicle movements.
        """
        self._update_traffic_signals()
        self._update_vehicle_positions()

    def _update_traffic_signals(self):
        """
        Manages the traffic light state machine (RED -> GREEN -> YELLOW -> RED).
        """
        current_time = time.time()
        elapsed_time = (current_time - self.last_signal_change_time) * 1000  # in ms

        active_lane = self.signal_lanes_order[self.current_green_lane_index]
        current_green_duration = self.green_signal_times[active_lane]

        if self.current_signal_color == "green" and elapsed_time >= current_green_duration:
            # Switch from GREEN to YELLOW
            self.current_signal_color = "yellow"
            self.last_signal_change_time = current_time
        elif self.current_signal_color == "yellow" and elapsed_time >= config.YELLOW_SIGNAL_TIME:
            # Switch from YELLOW to RED and prepare for the next lane to turn green
            self.current_signal_color = "red"
            self.last_signal_change_time = current_time
            # Move to the next lane in the cycle
            self.current_green_lane_index = (self.current_green_lane_index + 1) % len(self.signal_lanes_order)
        elif self.current_signal_color == "red":
            # After a brief red, switch the new lane to GREEN
            self.current_signal_color = "green"
            self.last_signal_change_time = current_time

    def _update_vehicle_positions(self):
        """
        Updates the position of each vehicle based on the current traffic signal state.
        """
        active_lane_name = self.signal_lanes_order[self.current_green_lane_index]
        
        # Loop through all lanes and their vehicles
        for lane_name, vehicle_list in self.lanes.items():
            # Vehicles in the active green lane can move
            is_green = (lane_name == active_lane_name and self.current_signal_color == "green")
            
            # Update each vehicle in the list
            for vehicle in vehicle_list:
                vehicle.move(is_green)

    def get_simulation_state(self):
        """
        Returns the current state of the simulation for rendering.

        Returns:
            dict: A dictionary containing the signal states and all vehicle sprites.
        """
        signal_state = {lane: "red" for lane in self.signal_lanes_order}
        active_lane = self.signal_lanes_order[self.current_green_lane_index]
        signal_state[active_lane] = self.current_signal_color

        all_vehicles = pygame.sprite.Group(
            self.lanes['right'] + self.lanes['left'] + self.lanes['up'] + self.lanes['down']
        )
        
        return {
            "signals": signal_state,
            "vehicles": all_vehicles
        }
