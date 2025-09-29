import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { 
  Car, 
  Truck, 
  AlertTriangle, 
  Activity, 
  Clock,
  Upload,
  Play,
  Pause,
  Settings
} from 'lucide-react';
import { useDropzone } from 'react-dropzone';
import { Line, Bar, Doughnut } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
} from 'chart.js';
import toast from 'react-hot-toast';

import { TrafficAPI } from '../services/trafficAPI';
import { WebSocketService } from '../services/websocketService';
import { TrafficIntersection } from './TrafficIntersection';
import { VehicleDetectionResults } from './VehicleDetectionResults';
import { AnalyticsDashboard } from './AnalyticsDashboard';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
);

interface TrafficDashboardProps {}

export const TrafficDashboard: React.FC<TrafficDashboardProps> = () => {
  const [intersectionStatus, setIntersectionStatus] = useState(null);
  const [detectionResults, setDetectionResults] = useState(null);
  const [analyticsData, setAnalyticsData] = useState(null);
  const [isSimulationRunning, setIsSimulationRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('live');

  // WebSocket connection for real-time updates
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

  // File upload for vehicle detection
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: {
      'image/*': ['.jpeg', '.jpg', '.png']
    },
    onDrop: async (acceptedFiles) => {
      if (acceptedFiles.length === 0) return;
      
      setIsLoading(true);
      try {
        const formData = new FormData();
        formData.append('image', acceptedFiles[0]);
        
        const result = await TrafficAPI.detectVehicles(formData);
        setDetectionResults(result);
        toast.success('Vehicle detection completed!');
      } catch (error) {
        toast.error('Failed to analyze image');
        console.error('Detection error:', error);
      } finally {
        setIsLoading(false);
      }
    },
  });

  const handleStartSimulation = async () => {
    try {
      setIsLoading(true);
      await TrafficAPI.startSimulation();
      setIsSimulationRunning(true);
      toast.success('Simulation started!');
    } catch (error) {
      toast.error('Failed to start simulation');
    } finally {
      setIsLoading(false);
    }
  };

  const handleStopSimulation = async () => {
    try {
      setIsSimulationRunning(false);
      toast.success('Simulation stopped!');
    } catch (error) {
      toast.error('Failed to stop simulation');
    }
  };

  const loadAnalytics = async () => {
    try {
      const data = await TrafficAPI.getAnalytics();
      setAnalyticsData(data);
    } catch (error) {
      toast.error('Failed to load analytics');
    }
  };

  useEffect(() => {
    if (activeTab === 'analytics') {
      loadAnalytics();
    }
  }, [activeTab]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      {/* Header */}
      <header className="bg-white shadow-lg border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div className="flex items-center space-x-3">
              <div className="flex-shrink-0">
                <Car className="h-8 w-8 text-blue-600" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">
                  AI Traffic Management System
                </h1>
                <p className="text-sm text-gray-500">
                  Intelligent traffic optimization with real-time AI
                </p>
              </div>
            </div>
            
            <div className="flex items-center space-x-4">
              {/* Simulation Controls */}
              <div className="flex items-center space-x-2">
                <button
                  onClick={isSimulationRunning ? handleStopSimulation : handleStartSimulation}
                  disabled={isLoading}
                  className={`flex items-center space-x-2 px-4 py-2 rounded-lg font-medium transition-colors ${
                    isSimulationRunning 
                      ? 'bg-red-600 hover:bg-red-700 text-white' 
                      : 'bg-green-600 hover:bg-green-700 text-white'
                  } disabled:opacity-50`}
                >
                  {isSimulationRunning ? (
                    <>
                      <Pause className="h-4 w-4" />
                      <span>Stop</span>
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4" />
                      <span>Start</span>
                    </>
                  )}
                </button>
              </div>

              {/* Status Indicator */}
              <div className="flex items-center space-x-2">
                <div className={`h-3 w-3 rounded-full ${
                  isSimulationRunning ? 'bg-green-500 animate-pulse' : 'bg-gray-400'
                }`} />
                <span className="text-sm font-medium text-gray-700">
                  {isSimulationRunning ? 'Live' : 'Stopped'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Navigation Tabs */}
      <nav className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex space-x-8">
            {[
              { id: 'live', name: 'Live Traffic', icon: Activity },
              { id: 'detection', name: 'Vehicle Detection', icon: Car },
              { id: 'analytics', name: 'Analytics', icon: Clock },
              { id: 'settings', name: 'Settings', icon: Settings },
            ].map(({ id, name, icon: Icon }) => (
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
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          {/* Live Traffic Tab */}
          {activeTab === 'live' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Traffic Intersection Visualization */}
                <div className="bg-white rounded-xl shadow-lg p-6">
                  <h2 className="text-xl font-semibold text-gray-900 mb-4">
                    Intersection Status
                  </h2>
                  <TrafficIntersection 
                    status={intersectionStatus}
                    isSimulationRunning={isSimulationRunning}
                  />
                </div>

                {/* Real-time Metrics */}
                <div className="space-y-4">
                  <div className="bg-white rounded-xl shadow-lg p-6">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">
                      Current Metrics
                    </h3>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="text-center">
                        <div className="text-2xl font-bold text-blue-600">
                          {intersectionStatus?.total_vehicles || 0}
                        </div>
                        <div className="text-sm text-gray-500">Total Vehicles</div>
                      </div>
                      <div className="text-center">
                        <div className="text-2xl font-bold text-green-600">
                          {intersectionStatus?.efficiency_score ? 
                            `${(intersectionStatus.efficiency_score * 100).toFixed(1)}%` : '0%'
                          }
                        </div>
                        <div className="text-sm text-gray-500">Efficiency</div>
                      </div>
                    </div>
                  </div>

                  {/* Emergency Alert */}
                  {intersectionStatus?.emergency_mode && (
                    <motion.div
                      initial={{ scale: 0.9 }}
                      animate={{ scale: 1 }}
                      className="bg-red-50 border border-red-200 rounded-xl p-4"
                    >
                      <div className="flex items-center space-x-3">
                        <AlertTriangle className="h-6 w-6 text-red-600" />
                        <div>
                          <h4 className="font-semibold text-red-900">
                            Emergency Mode Active
                          </h4>
                          <p className="text-sm text-red-700">
                            Emergency vehicle detected - priority signals engaged
                          </p>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Vehicle Detection Tab */}
          {activeTab === 'detection' && (
            <div className="space-y-6">
              {/* Upload Zone */}
              <div className="bg-white rounded-xl shadow-lg p-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-4">
                  Vehicle Detection Analysis
                </h2>
                
                <div
                  {...getRootProps()}
                  className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                    isDragActive 
                      ? 'border-blue-400 bg-blue-50' 
                      : 'border-gray-300 hover:border-gray-400'
                  }`}
                >
                  <input {...getInputProps()} />
                  <Upload className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                  <div className="text-lg font-medium text-gray-900 mb-2">
                    {isDragActive ? 'Drop image here' : 'Upload intersection image'}
                  </div>
                  <p className="text-gray-500">
                    Drag and drop an image or click to select
                  </p>
                  <p className="text-sm text-gray-400 mt-2">
                    Supports JPEG, PNG formats
                  </p>
                </div>
              </div>

              {/* Detection Results */}
              {detectionResults && (
                <VehicleDetectionResults results={detectionResults} />
              )}
            </div>
          )}

          {/* Analytics Tab */}
          {activeTab === 'analytics' && (
            <AnalyticsDashboard data={analyticsData} />
          )}

          {/* Settings Tab */}
          {activeTab === 'settings' && (
            <div className="bg-white rounded-xl shadow-lg p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">
                System Configuration
              </h2>
              <p className="text-gray-500">
                Configuration settings will be implemented here.
              </p>
            </div>
          )}
        </motion.div>
      </main>
    </div>
  );
};
