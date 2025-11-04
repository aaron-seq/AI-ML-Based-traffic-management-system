import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Car,
  Activity,
  Clock,
  Settings
} from 'lucide-react';
import toast from 'react-hot-toast';

import { TrafficAPI } from '../services/trafficAPI';
import { WebSocketService } from '../services/websocketService';
import { TrafficIntersection } from './TrafficIntersection';
import { VehicleDetectionResults } from './VehicleDetectionResults';
import { AnalyticsDashboard } from './AnalyticsDashboard';
import { FileUploader } from './FileUploader';
import { SimulationControls } from './SimulationControls';

const navTabs = [
  { id: 'live', name: 'Live Traffic', icon: Activity },
  { id: 'detection', name: 'Vehicle Detection', icon: Car },
  { id: 'analytics', name: 'Analytics', icon: Clock },
  { id: 'settings', name: 'Settings', icon: Settings },
];

export const TrafficDashboard: React.FC = () => {
  const [intersectionStatus, setIntersectionStatus] = useState(null);
  const [detectionResults, setDetectionResults] = useState(null);
  const [analyticsData, setAnalyticsData] = useState(null);
  const [isSimulationRunning, setIsSimulationRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('live');

  useEffect(() => {
    const wsService = new WebSocketService('ws://localhost:8000/ws/traffic-updates');
    
    wsService.onMessage((data) => {
      if (data.type === 'intersection_status') {
        setIntersectionStatus(data.data);
      } else if (data.type === 'vehicle_detection') {
        setDetectionResults(data.data);
        toast.success(`Detected ${data.data.total_vehicles} vehicles!`);
      } else if (data.type === 'emergency_alert') {
        toast.error(`Emergency vehicle detected in ${data.data.detected_lane} lane!`);
      }
    });

    return () => wsService.disconnect();
  }, []);

  const handleFileUpload = useCallback(async (file: File) => {
    setIsLoading(true);
    try {
      const formData = new FormData();
      formData.append('image', file);

      const result = await TrafficAPI.detectVehicles(formData);
      setDetectionResults(result);
      toast.success('Vehicle detection completed!');
    } catch (error) {
      toast.error('Failed to analyze image');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const toggleSimulation = useCallback(async () => {
    setIsLoading(true);
    try {
      if (isSimulationRunning) {
        await TrafficAPI.stopSimulation();
        toast.success('Simulation stopped!');
      } else {
        await TrafficAPI.startSimulation();
        toast.success('Simulation started!');
      }
      setIsSimulationRunning(!isSimulationRunning);
    } catch (error) {
      toast.error(`Failed to ${isSimulationRunning ? 'stop' : 'start'} simulation`);
    } finally {
      setIsLoading(false);
    }
  }, [isSimulationRunning]);

  useEffect(() => {
    if (activeTab === 'analytics') {
      TrafficAPI.getAnalytics().then(setAnalyticsData).catch(() => toast.error('Failed to load analytics'));
    }
  }, [activeTab]);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <div className="flex items-center space-x-3">
            <Car className="h-8 w-8 text-blue-600" />
            <div>
              <h1 className="text-2xl font-bold text-gray-900">AI Traffic Management</h1>
              <p className="text-sm text-gray-500">Real-time traffic optimization</p>
            </div>
          </div>
          <SimulationControls
            isRunning={isSimulationRunning}
            onToggle={toggleSimulation}
            isLoading={isLoading}
          />
        </div>
      </header>

      <nav className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex space-x-8">
          {navTabs.map(({ id, name, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center space-x-2 py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <Icon className="h-4 w-4" />
              <span>{name}</span>
            </button>
          ))}
        </div>
      </nav>

      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          {activeTab === 'live' && <TrafficIntersection status={intersectionStatus} />}
          {activeTab === 'detection' && (
            <>
              <FileUploader onFileUpload={handleFileUpload} isLoading={isLoading} />
              {detectionResults && <VehicleDetectionResults results={detectionResults} />}
            </>
          )}
          {activeTab === 'analytics' && <AnalyticsDashboard data={analyticsData} />}
          {activeTab === 'settings' && (
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold text-gray-900">System Configuration</h2>
              <p className="text-gray-600 mt-2">Configuration settings will be available in a future update.</p>
            </div>
          )}
        </motion.div>
      </main>
    </div>
  );
};
