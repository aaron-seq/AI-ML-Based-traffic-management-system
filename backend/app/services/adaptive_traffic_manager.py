"""
Adaptive Traffic Management Service
Dynamically adjusts traffic signal timings based on real-time data
"""

import asyncio
from typing import Dict

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    IntersectionStatus, TrafficSignalState,
    LaneDirection, TrafficSignal
)


class AdaptiveTrafficManager(LoggerMixin):
    """Manages traffic flow by adjusting signal timings"""
    
    def __init__(self):
        super().__init__()
        self.intersection_status = IntersectionStatus(
            signals={},
            vehicle_counts={lane: 0 for lane in LaneDirection}
        )
        self._is_ready = False
        self._emergency_mode = False
        self._update_task: asyncio.Task = None
        self._initialize_signals()
    
    def _initialize_signals(self):
        """Initialize traffic signals to a default state"""
        for lane in LaneDirection:
            self.intersection_status.signals[lane] = TrafficSignal(
                direction=lane,
                state=TrafficSignalState.RED,
                remaining_time=99
            )
        # Set one direction to green initially
        self.intersection_status.signals[LaneDirection.NORTH].state = TrafficSignalState.GREEN
        self.intersection_status.signals[LaneDirection.NORTH].remaining_time = settings.default_green_signal_duration

    async def initialize(self) -> None:
        """Initialize traffic manager and start update loop"""
        self.logger.info("Initializing adaptive traffic manager")
        self._is_ready = True
        self._update_task = asyncio.create_task(self._traffic_update_loop())
        self.logger.info("Adaptive traffic manager initialized")

    async def get_current_status(self) -> IntersectionStatus:
        """Get current status of the intersection"""
        return self.intersection_status
    
    async def update_vehicle_counts(self, lane_counts: Dict[str, int]) -> None:
        """Update vehicle counts from detection service"""
        for lane, count in lane_counts.items():
            if lane in self.intersection_status.vehicle_counts:
                self.intersection_status.vehicle_counts[lane] = count

    async def activate_emergency_override(self, lane: LaneDirection) -> None:
        """Activate emergency override for a specific lane"""
        self._emergency_mode = True
        self.logger.warning(f"Emergency override activated for lane: {lane.value}")
        
        # Set all signals to red, then specified lane to green
        for signal_lane in self.intersection_status.signals:
            self.intersection_status.signals[signal_lane].state = TrafficSignalState.RED
        
        self.intersection_status.signals[lane].state = TrafficSignalState.GREEN
        self.intersection_status.signals[lane].remaining_time = settings.emergency_override_duration
        
        # Schedule deactivation
        asyncio.create_task(self._deactivate_emergency_mode_after_delay())
        
    async def _deactivate_emergency_mode_after_delay(self):
        """Deactivate emergency mode after a delay"""
        await asyncio.sleep(settings.emergency_override_duration)
        self._emergency_mode = False
        self.logger.info("Emergency override deactivated")
        # Restore normal operation, might need a more sophisticated approach
        self._initialize_signals()

    async def _traffic_update_loop(self):
        """Main loop for updating traffic signal timings"""
        while self._is_ready:
            try:
                if not self._emergency_mode:
                    await self._adjust_signal_timings()
                
                await asyncio.sleep(settings.websocket_update_interval)
            
            except asyncio.CancelledError:
                self.logger.info("Traffic update loop cancelled")
                break
            except Exception as error:
                self.log_error_with_context(error, "_traffic_update_loop")
                # Avoid crashing the loop on transient errors
                await asyncio.sleep(5)
    
    async def _adjust_signal_timings(self):
        """Core logic for adjusting signal timings based on traffic"""
        # This is a simplified logic. A real-world system would be much more complex.
        
        green_lanes = [
            lane for lane, signal in self.intersection_status.signals.items()
            if signal.state == TrafficSignalState.GREEN
        ]
        
        if not green_lanes:
            # If no lane is green (e.g., after emergency), start a new cycle
            self.intersection_status.signals[LaneDirection.NORTH].state = TrafficSignalState.GREEN
            self.intersection_status.signals[LaneDirection.NORTH].remaining_time = settings.default_green_signal_duration
            return

        current_green_lane = green_lanes[0]
        
        # Decrement timer
        self.intersection_status.signals[current_green_lane].remaining_time -= settings.websocket_update_interval

        if self.intersection_status.signals[current_green_lane].remaining_time <= 0:
            # Transition to next phase
            self.intersection_status.signals[current_green_lane].state = TrafficSignalState.YELLOW
            self.intersection_status.signals[current_green_lane].remaining_time = 5 # Yellow light duration
            
            # Simple rotation logic
            next_lane_map = {
                LaneDirection.NORTH: LaneDirection.EAST,
                LaneDirection.EAST: LaneDirection.SOUTH,
                LaneDirection.SOUTH: LaneDirection.WEST,
                LaneDirection.WEST: LaneDirection.NORTH
            }
            next_green_lane = next_lane_map[current_green_lane]
            
            # After yellow, set current to red and next to green
            await asyncio.sleep(5)
            self.intersection_status.signals[current_green_lane].state = TrafficSignalState.RED
            self.intersection_status.signals[next_green_lane].state = TrafficSignalState.GREEN

            # Adjust duration based on traffic
            duration = self._calculate_green_duration(next_green_lane)
            self.intersection_status.signals[next_green_lane].remaining_time = duration
    
    def _calculate_green_duration(self, lane: LaneDirection) -> int:
        """Calculate green light duration based on vehicle count"""
        base_duration = settings.default_green_signal_duration
        vehicle_count = self.intersection_status.vehicle_counts.get(lane, 0)
        
        # Add 2 seconds for each vehicle, up to a max of 30 extra seconds
        additional_time = min(vehicle_count * 2, 30)
        
        return base_duration + additional_time

    def is_ready(self) -> bool:
        """Check if traffic manager is ready"""
        return self._is_ready
    
    async def cleanup(self) -> None:
        """Cleanup resources, stop background tasks"""
        self.logger.info("Cleaning up adaptive traffic manager")
        self._is_ready = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Adaptive traffic manager cleaned up")
