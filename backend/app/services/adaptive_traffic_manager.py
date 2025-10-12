"""
Adaptive Traffic Management Service
Intelligent traffic signal optimization based on real-time vehicle detection
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    IntersectionStatus, TrafficSignal, TrafficSignalState, 
    LaneDirection, EmergencyAlert, VehicleDetectionResult
)


class AdaptiveTrafficManager(LoggerMixin):
    """Intelligent traffic management system with adaptive signal timing"""
    
    def __init__(self):
        super().__init__()
        self.intersection_status = IntersectionStatus()
        self.emergency_alerts: Dict[str, EmergencyAlert] = {}
        self.signal_update_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.performance_metrics = {
            'total_cycles_completed': 0,
            'emergency_overrides': 0,
            'average_cycle_time': 0.0,
            'optimization_events': 0
        }
        
        # Initialize traffic signals
        self._initialize_traffic_signals()
    
    def _initialize_traffic_signals(self) -> None:
        """Initialize traffic signals for all lane directions"""
        for lane in LaneDirection:
            self.intersection_status.traffic_signals[lane] = TrafficSignal(
                signal_id=f"{lane.value}_signal",
                direction=lane,
                current_state=TrafficSignalState.RED,
                remaining_time=settings.default_green_signal_duration,
                cycle_duration=settings.default_green_signal_duration
            )
        
        # Start with North-South green cycle
        self.intersection_status.traffic_signals[LaneDirection.NORTH].current_state = TrafficSignalState.GREEN
        self.intersection_status.traffic_signals[LaneDirection.SOUTH].current_state = TrafficSignalState.GREEN
        
        self.logger.info("Traffic signals initialized")
    
    async def start_simulation(self) -> None:
        """Start the adaptive traffic management simulation"""
        if self.is_running:
            self.logger.warning("Traffic management simulation already running")
            return
        
        self.is_running = True
        self.logger.info("Starting adaptive traffic management simulation")
        
        # Start the signal update loop
        self.signal_update_task = asyncio.create_task(self._signal_update_loop())
    
    async def stop_simulation(self) -> None:
        """Stop the traffic management simulation"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        if self.signal_update_task:
            self.signal_update_task.cancel()
            try:
                await self.signal_update_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Traffic management simulation stopped")
    
    async def _signal_update_loop(self) -> None:
        """Main loop for updating traffic signals"""
        try:
            while self.is_running:
                await self._update_signal_states()
                await self._check_emergency_overrides()
                await asyncio.sleep(1)  # Update every second
                
        except asyncio.CancelledError:
            self.logger.info("Signal update loop cancelled")
        except Exception as error:
            self.log_error_with_context(error, "signal_update_loop")
    
    async def _update_signal_states(self) -> None:
        """Update traffic signal states based on timing and conditions"""
        current_time = datetime.utcnow()
        
        for lane, signal in self.intersection_status.traffic_signals.items():
            # Decrease remaining time
            if signal.remaining_time > 0:
                signal.remaining_time -= 1
            
            # Handle state transitions
            if signal.remaining_time <= 0:
                await self._transition_signal_state(signal)
            
            signal.last_updated = current_time
        
        self.intersection_status.last_updated = current_time
    
    async def _transition_signal_state(self, signal: TrafficSignal) -> None:
        """Transition traffic signal to next state"""
        current_state = signal.current_state
        
        if current_state == TrafficSignalState.GREEN:
            # Green to Yellow
            signal.current_state = TrafficSignalState.YELLOW
            signal.remaining_time = settings.yellow_signal_duration
            signal.next_state = TrafficSignalState.RED
            
        elif current_state == TrafficSignalState.YELLOW:
            # Yellow to Red
            signal.current_state = TrafficSignalState.RED
            signal.remaining_time = self._calculate_red_duration(signal.direction)
            signal.next_state = None
            
        elif current_state == TrafficSignalState.RED:
            # Red to Green (if conditions are met)
            if self._should_activate_signal(signal.direction):
                signal.current_state = TrafficSignalState.GREEN
                signal.remaining_time = self._calculate_green_duration(signal.direction)
                signal.next_state = TrafficSignalState.YELLOW
        
        self.logger.debug(
            f"Signal {signal.signal_id} transitioned to {signal.current_state.value}"
        )
    
    def _should_activate_signal(self, lane: LaneDirection) -> bool:
        """Determine if a signal should be activated based on traffic conditions"""
        # Check if perpendicular lanes have finished their cycle
        perpendicular_lanes = self._get_perpendicular_lanes(lane)
        
        for perp_lane in perpendicular_lanes:
            perp_signal = self.intersection_status.traffic_signals[perp_lane]
            if perp_signal.current_state in [TrafficSignalState.GREEN, TrafficSignalState.YELLOW]:
                return False
        
        return True
    
    def _get_perpendicular_lanes(self, lane: LaneDirection) -> List[LaneDirection]:
        """Get perpendicular lanes to the given lane"""
        if lane in [LaneDirection.NORTH, LaneDirection.SOUTH]:
            return [LaneDirection.EAST, LaneDirection.WEST]
        else:
            return [LaneDirection.NORTH, LaneDirection.SOUTH]
    
    def _calculate_green_duration(self, lane: LaneDirection) -> int:
        """Calculate optimal green signal duration based on traffic density"""
        vehicle_count = self.intersection_status.vehicle_counts.get(lane, 0)
        
        # Base duration
        base_duration = settings.default_green_signal_duration
        
        # Adaptive adjustment based on vehicle count
        if vehicle_count == 0:
            duration = settings.minimum_green_duration
        elif vehicle_count <= 3:
            duration = base_duration
        elif vehicle_count <= 8:
            duration = int(base_duration * 1.5)
        else:
            duration = settings.maximum_green_duration
        
        # Ensure within bounds
        duration = max(settings.minimum_green_duration, 
                      min(duration, settings.maximum_green_duration))
        
        self.logger.debug(
            f"Calculated green duration for {lane.value}: {duration}s (vehicles: {vehicle_count})"
        )
        
        return duration
    
    def _calculate_red_duration(self, lane: LaneDirection) -> int:
        """Calculate red signal duration (time for other lanes to cycle)"""
        # Calculate time needed for perpendicular lanes to complete their cycle
        perpendicular_lanes = self._get_perpendicular_lanes(lane)
        max_duration = 0
        
        for perp_lane in perpendicular_lanes:
            vehicle_count = self.intersection_status.vehicle_counts.get(perp_lane, 0)
            green_time = self._calculate_green_duration(perp_lane)
            total_time = green_time + settings.yellow_signal_duration
            max_duration = max(max_duration, total_time)
        
        return max_duration
    
    async def update_vehicle_counts(self, lane_counts: Dict[LaneDirection, int]) -> None:
        """Update vehicle counts from detection results"""
        self.intersection_status.vehicle_counts = lane_counts
        self.intersection_status.total_vehicles = sum(lane_counts.values())
        self.intersection_status.last_detection_time = datetime.utcnow()
        
        # Trigger optimization if needed
        await self._optimize_signal_timing()
        
        self.logger.info(f"Updated vehicle counts: {lane_counts}")
    
    async def _optimize_signal_timing(self) -> None:
        """Optimize signal timing based on current traffic conditions"""
        if not self.is_running:
            return
        
        # Find lane with highest vehicle count
        max_vehicles = 0
        busiest_lane = None
        
        for lane, count in self.intersection_status.vehicle_counts.items():
            if count > max_vehicles:
                max_vehicles = count
                busiest_lane = lane
        
        # If there's a significantly busier lane, prioritize it
        if busiest_lane and max_vehicles > 0:
            current_signal = self.intersection_status.traffic_signals[busiest_lane]
            
            # If the busiest lane is red and has high traffic, consider early activation
            if (current_signal.current_state == TrafficSignalState.RED and 
                max_vehicles >= 5 and
                self._can_prioritize_lane(busiest_lane)):
                
                await self._prioritize_lane(busiest_lane)
                self.performance_metrics['optimization_events'] += 1
    
    def _can_prioritize_lane(self, lane: LaneDirection) -> bool:
        """Check if a lane can be prioritized without disrupting traffic flow"""
        perpendicular_lanes = self._get_perpendicular_lanes(lane)
        
        for perp_lane in perpendicular_lanes:
            perp_signal = self.intersection_status.traffic_signals[perp_lane]
            # Don't interrupt if perpendicular lane just started green cycle
            if (perp_signal.current_state == TrafficSignalState.GREEN and 
                perp_signal.remaining_time > settings.minimum_green_duration):
                return False
        
        return True
    
    async def _prioritize_lane(self, lane: LaneDirection) -> None:
        """Prioritize a specific lane by adjusting signal timing"""
        # Shorten perpendicular lanes' green time
        perpendicular_lanes = self._get_perpendicular_lanes(lane)
        
        for perp_lane in perpendicular_lanes:
            perp_signal = self.intersection_status.traffic_signals[perp_lane]
            if perp_signal.current_state == TrafficSignalState.GREEN:
                # Reduce to minimum green time
                perp_signal.remaining_time = min(
                    perp_signal.remaining_time,
                    settings.minimum_green_duration
                )
        
        self.logger.info(f"Prioritized lane {lane.value} due to high traffic density")
    
    async def handle_emergency_override(self, alert: EmergencyAlert) -> None:
        """Handle emergency vehicle detection and override signals"""
        self.emergency_alerts[alert.alert_id] = alert
        self.intersection_status.emergency_mode_active = True
        
        # Immediately switch emergency lane to green
        emergency_lane = alert.detected_lane
        emergency_signal = self.intersection_status.traffic_signals[emergency_lane]
        
        # Set all other signals to red
        for lane, signal in self.intersection_status.traffic_signals.items():
            if lane != emergency_lane:
                signal.current_state = TrafficSignalState.RED
                signal.remaining_time = alert.override_duration
        
        # Set emergency lane to green
        emergency_signal.current_state = TrafficSignalState.GREEN
        emergency_signal.remaining_time = alert.override_duration
        
        self.performance_metrics['emergency_overrides'] += 1
        
        self.logger.warning(
            f"Emergency override activated for {emergency_lane.value} lane "
            f"(Alert ID: {alert.alert_id})"
        )
        
        # Schedule automatic resolution
        asyncio.create_task(self._resolve_emergency_alert(alert.alert_id, alert.override_duration))
    
    async def _resolve_emergency_alert(self, alert_id: str, delay: int) -> None:
        """Automatically resolve emergency alert after specified delay"""
        await asyncio.sleep(delay)
        
        if alert_id in self.emergency_alerts:
            self.emergency_alerts[alert_id].is_active = False
            self.emergency_alerts[alert_id].resolved_at = datetime.utcnow()
            del self.emergency_alerts[alert_id]
            
            # Check if there are other active emergencies
            if not self.emergency_alerts:
                self.intersection_status.emergency_mode_active = False
                self.logger.info(f"Emergency alert {alert_id} resolved")
    
    async def _check_emergency_overrides(self) -> None:
        """Check for expired emergency overrides"""
        current_time = datetime.utcnow()
        expired_alerts = []
        
        for alert_id, alert in self.emergency_alerts.items():
            if alert.is_active and alert.get_time_since_alert() > alert.override_duration:
                expired_alerts.append(alert_id)
        
        for alert_id in expired_alerts:
            await self._resolve_emergency_alert(alert_id, 0)
    
    async def get_current_status(self) -> IntersectionStatus:
        """Get current intersection status"""
        return self.intersection_status
    
    async def update_configuration(self, config: Dict) -> None:
        """Update traffic management configuration"""
        # Update settings based on provided configuration
        for key, value in config.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        self.logger.info(f"Configuration updated: {config}")
    
    def is_ready(self) -> bool:
        """Check if traffic manager is ready"""
        return len(self.intersection_status.traffic_signals) == len(LaneDirection)
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        return self.performance_metrics.copy()
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        await self.stop_simulation()
        self.emergency_alerts.clear()
        self.logger.info("Traffic manager cleanup completed")