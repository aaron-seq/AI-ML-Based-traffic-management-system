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
    LaneDirection, TrafficSnapshot
)


class TrafficAnalyticsService(LoggerMixin):
    """Advanced traffic analytics and reporting service"""
    
    def __init__(self, max_history_size: int = 1000):
        super().__init__()
        self.max_history_size = max_history_size
        self.detection_history: deque = deque(maxlen=max_history_size)
        self.traffic_snapshots: deque = deque(maxlen=max_history_size)
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
    
    async def record_traffic_snapshot(self, snapshot: TrafficSnapshot) -> None:
        """Record a complete traffic system snapshot"""
        try:
            self.traffic_snapshots.append(snapshot)
            
            # Update emergency event counter
            if snapshot.has_active_emergencies():
                self.performance_metrics['emergency_events'] += 1
            
            self.logger.debug(f"Recorded traffic snapshot: {snapshot.snapshot_id}")
            
        except Exception as error:
            self.log_error_with_context(error, "record_traffic_snapshot")
    
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
            self.performance_metrics['peak_traffic_time'] = detection_result.detection_timestamp
        
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
            'detection_count': len(self.detection_history),
            'snapshot_count': len(self.traffic_snapshots)
        }
        
        # Recent traffic analysis (last 10 detections)
        recent_detections = list(self.detection_history)[-10:] if self.detection_history else []
        if recent_detections:
            summary['recent_traffic'] = {
                'average_vehicles': sum(r['result'].total_vehicles for r in recent_detections) / len(recent_detections),
                'peak_vehicles': max(r['result'].total_vehicles for r in recent_detections),
                'lane_distribution': self._calculate_lane_distribution(recent_detections),
                'emergency_vehicles_detected': sum(1 for r in recent_detections if r['result'].has_emergency_vehicles)
            }
        
        # Traffic flow analysis
        if len(self.detection_history) >= 2:
            summary['traffic_flow'] = await self._analyze_traffic_flow()
        
        # System health indicators
        summary['system_health'] = {
            'detection_rate': len(self.detection_history) / max(1, (current_time - self.service_start_time).total_seconds() / 60),  # detections per minute
            'average_processing_time': self._calculate_average_processing_time(),
            'data_points_collected': len(self.detection_history) + len(self.traffic_snapshots)
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
            'peak_vehicles': hourly_patterns.get(peak_hour, 0) if peak_hour else 0,
            'emergency_events': sum(1 for d in daily_detections if d.has_emergency_vehicles)
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
    
    async def _analyze_traffic_flow(self) -> Dict[str, Any]:
        """Analyze traffic flow patterns"""
        if len(self.detection_history) < 2:
            return {}
        
        recent_records = list(self.detection_history)[-20:]  # Last 20 records
        
        # Calculate traffic trend
        first_half = recent_records[:len(recent_records)//2]
        second_half = recent_records[len(recent_records)//2:]
        
        first_avg = sum(r['result'].total_vehicles for r in first_half) / len(first_half)
        second_avg = sum(r['result'].total_vehicles for r in second_half) / len(second_half)
        
        trend = 'increasing' if second_avg > first_avg else 'decreasing' if second_avg < first_avg else 'stable'
        trend_percentage = abs((second_avg - first_avg) / max(first_avg, 1)) * 100
        
        # Processing time trend
        processing_times = [r['result'].processing_time for r in recent_records]
        avg_processing_time = sum(processing_times) / len(processing_times)
        
        return {
            'trend': trend,
            'trend_percentage': trend_percentage,
            'average_processing_time': avg_processing_time,
            'data_quality_score': self._calculate_data_quality_score(recent_records)
        }
    
    def _calculate_average_processing_time(self) -> float:
        """Calculate average processing time across all detections"""
        if not self.detection_history:
            return 0.0
        
        total_time = sum(record['result'].processing_time for record in self.detection_history)
        return total_time / len(self.detection_history)
    
    def _calculate_data_quality_score(self, records: List[Dict]) -> float:
        """Calculate data quality score based on confidence levels"""
        if not records:
            return 0.0
        
        total_confidence = 0.0
        total_detections = 0
        
        for record in records:
            confidence_scores = record['result'].confidence_scores
            if confidence_scores:
                total_confidence += sum(confidence_scores)
                total_detections += len(confidence_scores)
        
        if total_detections == 0:
            return 0.0
        
        return (total_confidence / total_detections) * 100
    
    async def get_traffic_heatmap_data(self, hours: int = 24) -> Dict[str, Any]:
        """Generate traffic heatmap data for visualization"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Filter recent detections
        recent_detections = [
            record for record in self.detection_history
            if record['timestamp'] >= cutoff_time
        ]
        
        if not recent_detections:
            return {'error': 'No recent data available'}
        
        # Group by hour and lane
        heatmap_data = defaultdict(lambda: defaultdict(int))
        
        for record in recent_detections:
            hour = record['timestamp'].strftime('%H')
            for lane, count in record['result'].lane_counts.items():
                heatmap_data[hour][lane.value] += count
        
        return {
            'time_range': f'Last {hours} hours',
            'data': dict(heatmap_data),
            'peak_hour': max(heatmap_data.items(), key=lambda x: sum(x[1].values()))[0] if heatmap_data else None
        }
    
    async def get_performance_report(self) -> Dict[str, Any]:
        """Generate detailed performance report"""
        current_time = datetime.utcnow()
        uptime = current_time - self.service_start_time
        
        return {
            'service_uptime': {
                'total_seconds': uptime.total_seconds(),
                'hours': uptime.total_seconds() / 3600,
                'days': uptime.days
            },
            'data_collection': {
                'total_detections': len(self.detection_history),
                'total_snapshots': len(self.traffic_snapshots),
                'detection_rate_per_minute': len(self.detection_history) / max(1, uptime.total_seconds() / 60)
            },
            'traffic_insights': {
                'total_vehicles_detected': sum(r['result'].total_vehicles for r in self.detection_history),
                'average_processing_time': self._calculate_average_processing_time(),
                'data_quality_score': self._calculate_data_quality_score(list(self.detection_history))
            },
            'system_efficiency': {
                'memory_usage_mb': len(self.detection_history) * 0.1,  # Estimated
                'cache_hit_rate': 95.0,  # Placeholder
                'error_rate': 0.01  # Placeholder
            }
        }
    
    def is_ready(self) -> bool:
        """Check if analytics service is ready"""
        return True
    
    async def cleanup(self) -> None:
        """Cleanup analytics service resources"""
        self.detection_history.clear()
        self.traffic_snapshots.clear()
        self.hourly_traffic_data.clear()
        self.logger.info("Analytics service cleanup completed")