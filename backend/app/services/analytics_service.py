"""
Traffic Analytics Service
Provides traffic data analysis, reporting, and performance metrics
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict, deque

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    VehicleDetectionResult, IntersectionStatus, 
    LaneDirection
)


class TrafficAnalyticsService(LoggerMixin):
    """Advanced traffic analytics and reporting service"""
    
    def __init__(self, max_history_size: int = 1000):
        super().__init__()
        self._is_ready = False
        self.max_history_size = max_history_size
        self.detection_history: deque = deque(maxlen=max_history_size)
        self.performance_metrics = {
            'total_detections': 0,
            'average_vehicles_per_detection': 0.0,
            'peak_traffic_time': None,
            'busiest_lane': None,
            'emergency_events': 0,
            'system_uptime': 0.0
        }
        self.hourly_traffic_data = defaultdict(list)
        self.daily_summaries = {}
        self.service_start_time = datetime.utcnow()
    
    async def initialize(self) -> None:
        """Initialize analytics service"""
        self._is_ready = True
        self.logger.info("Traffic analytics service initialized")
    
    async def record_detection(
        self, 
        detection_result: VehicleDetectionResult, 
        timestamp: datetime
    ) -> None:
        """Record a vehicle detection result for analysis"""
        try:
            # Add to detection history
            self.detection_history.append({
                'timestamp': timestamp,
                'result': detection_result
            })
            
            # Update performance metrics
            await self._update_performance_metrics(detection_result)
            
            # Update hourly data
            hour_key = timestamp.strftime('%Y-%m-%d_%H')
            self.hourly_traffic_data[hour_key].append(detection_result)
            
            self.logger.debug(f"Recorded detection with {detection_result.total_vehicles} vehicles")
            
        except Exception as error:
            self.log_error_with_context(error, "record_detection")
    
    async def _update_performance_metrics(self, detection_result: VehicleDetectionResult) -> None:
        """Update running performance metrics"""
        self.performance_metrics['total_detections'] += 1
        
        # Update average vehicles per detection
        total_detections = self.performance_metrics['total_detections']
        current_avg = self.performance_metrics['average_vehicles_per_detection']
        new_avg = (
            (current_avg * (total_detections - 1) + detection_result.total_vehicles) 
            / total_detections
        )
        self.performance_metrics['average_vehicles_per_detection'] = new_avg
        
        # Update peak traffic time
        if (self.performance_metrics['peak_traffic_time'] is None or 
            detection_result.total_vehicles > self._get_max_vehicles_from_history()):
            self.performance_metrics['peak_traffic_time'] = datetime.utcnow()
        
        # Update busiest lane
        busiest_lane = max(detection_result.lane_counts.items(), key=lambda x: x[1])
        if busiest_lane[1] > 0:
            self.performance_metrics['busiest_lane'] = busiest_lane[0]
        
        # Update system uptime
        uptime = (datetime.utcnow() - self.service_start_time).total_seconds()
        self.performance_metrics['system_uptime'] = uptime
    
    def _get_max_vehicles_from_history(self) -> int:
        """Get maximum vehicle count from detection history"""
        if not self.detection_history:
            return 0
        return max(record['result'].total_vehicles for record in self.detection_history)
    
    async def generate_summary(self, period: str = 'current') -> Dict[str, Any]:
        """Generate comprehensive analytics summary"""
        try:
            if period == 'current':
                return await self._generate_current_summary()
            elif period == 'hourly':
                return await self._generate_hourly_summary()
            elif period == 'daily':
                return await self._generate_daily_summary()
            else:
                return await self._generate_current_summary()
                
        except Exception as error:
            self.log_error_with_context(error, "generate_summary")
            return {'error': 'Failed to generate analytics summary'}
    
    async def _generate_current_summary(self) -> Dict[str, Any]:
        """Generate current session analytics summary"""
        current_time = datetime.utcnow()
        
        # Basic metrics
        summary = {
            'timestamp': current_time.isoformat(),
            'session_duration': (current_time - self.service_start_time).total_seconds(),
            'performance_metrics': self.performance_metrics.copy(),
            'detection_count': len(self.detection_history)
        }
        
        # Recent traffic analysis (last 10 detections)
        recent_detections = list(self.detection_history)[-10:] if self.detection_history else []
        if recent_detections:
            summary['recent_traffic'] = {
                'average_vehicles': sum(r['result'].total_vehicles for r in recent_detections) / len(recent_detections),
                'peak_vehicles': max(r['result'].total_vehicles for r in recent_detections),
                'lane_distribution': self._calculate_lane_distribution(recent_detections),
            }
        
        return summary
    
    async def _generate_hourly_summary(self) -> Dict[str, Any]:
        """Generate hourly traffic summary"""
        current_hour = datetime.utcnow().strftime('%Y-%m-%d_%H')
        hourly_data = self.hourly_traffic_data.get(current_hour, [])
        
        if not hourly_data:
            return {'message': 'No data available for current hour'}
        
        total_vehicles = sum(detection.total_vehicles for detection in hourly_data)
        avg_vehicles = total_vehicles / len(hourly_data)
        
        # Lane analysis
        lane_totals = defaultdict(int)
        for detection in hourly_data:
            for lane, count in detection.lane_counts.items():
                lane_totals[lane] += count
        
        return {
            'hour': current_hour,
            'total_detections': len(hourly_data),
            'total_vehicles': total_vehicles,
            'average_vehicles_per_detection': avg_vehicles,
            'lane_totals': dict(lane_totals),
            'busiest_lane': max(lane_totals.items(), key=lambda x: x[1])[0] if lane_totals else None,
            'peak_detection': max(hourly_data, key=lambda x: x.total_vehicles).total_vehicles if hourly_data else 0
        }
    
    async def _generate_daily_summary(self) -> Dict[str, Any]:
        """Generate daily traffic summary"""
        today = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Aggregate all hourly data for today
        daily_detections = []
        for hour_key, detections in self.hourly_traffic_data.items():
            if hour_key.startswith(today):
                daily_detections.extend(detections)
        
        if not daily_detections:
            return {'message': 'No data available for today'}
        
        total_vehicles = sum(detection.total_vehicles for detection in daily_detections)
        
        # Traffic patterns by hour
        hourly_patterns = {}
        for hour_key, detections in self.hourly_traffic_data.items():
            if hour_key.startswith(today):
                hour = hour_key.split('_')[1]
                hourly_patterns[hour] = sum(d.total_vehicles for d in detections)
        
        # Peak hours
        peak_hour = max(hourly_patterns.items(), key=lambda x: x[1])[0] if hourly_patterns else None
        
        return {
            'date': today,
            'total_detections': len(daily_detections),
            'total_vehicles': total_vehicles,
            'hourly_patterns': hourly_patterns,
            'peak_hour': peak_hour,
            'peak_vehicles': hourly_patterns.get(peak_hour, 0) if peak_hour else 0
        }
    
    def _calculate_lane_distribution(self, detections: List[Dict]) -> Dict[str, float]:
        """Calculate vehicle distribution across lanes"""
        lane_totals = defaultdict(int)
        total_vehicles = 0
        
        for record in detections:
            for lane, count in record['result'].lane_counts.items():
                lane_totals[lane] += count
                total_vehicles += count
        
        if total_vehicles == 0:
            return {lane.value: 0.0 for lane in LaneDirection}
        
        return {
            lane: (count / total_vehicles) * 100 
            for lane, count in lane_totals.items()
        }
    
    def is_ready(self) -> bool:
        """Check if analytics service is ready"""
        return self._is_ready
    
    async def cleanup(self) -> None:
        """Cleanup analytics service resources"""
        self._is_ready = False
        self.detection_history.clear()
        self.hourly_traffic_data.clear()
        self.logger.info("Analytics service cleanup completed")
