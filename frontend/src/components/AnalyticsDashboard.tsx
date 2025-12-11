import React from 'react';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    BarElement,
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend
);

interface AnalyticsDashboardProps {
    data: any;
}

export const AnalyticsDashboard: React.FC<AnalyticsDashboardProps> = ({ data }) => {
    // Mock data for visualization if null
    const chartData = {
        labels: ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00'],
        datasets: [
            {
                label: 'Traffic Density',
                data: data?.density_trend || [10, 5, 85, 60, 95, 40],
                borderColor: 'rgb(59, 130, 246)',
                backgroundColor: 'rgba(59, 130, 246, 0.5)',
                tension: 0.4,
            },
            {
                label: 'Efficiency Score',
                data: data?.efficiency_trend || [95, 98, 70, 85, 65, 90],
                borderColor: 'rgb(34, 197, 94)',
                backgroundColor: 'rgba(34, 197, 94, 0.5)',
                tension: 0.4,
            },
        ],
    };

    const laneData = {
        labels: ['North', 'South', 'East', 'West'],
        datasets: [
            {
                label: 'Average Vehicle Count',
                data: [450, 380, 510, 420], // Mock data
                backgroundColor: [
                    'rgba(255, 99, 132, 0.6)',
                    'rgba(54, 162, 235, 0.6)',
                    'rgba(255, 206, 86, 0.6)',
                    'rgba(75, 192, 192, 0.6)',
                ]
            }
        ]
    };

    return (
        <div className="space-y-6">
            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-white p-6 rounded-xl shadow-lg">
                    <h3 className="text-gray-500 text-sm font-medium">Total Vehicles Today</h3>
                    <p className="text-3xl font-bold text-gray-900 mt-2">{data?.total_vehicles_today || 1250}</p>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-lg">
                    <h3 className="text-gray-500 text-sm font-medium">Avg Wait Time</h3>
                    <p className="text-3xl font-bold text-blue-600 mt-2">{data?.average_wait_time || 45}s</p>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-lg">
                    <h3 className="text-gray-500 text-sm font-medium">System Efficiency</h3>
                    <p className="text-3xl font-bold text-green-600 mt-2">{(data?.efficiency || 0.85) * 100}%</p>
                </div>
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white p-6 rounded-xl shadow-lg">
                    <h3 className="text-lg font-semibold mb-4">Traffic Trends (24h)</h3>
                    <Line options={{ responsive: true }} data={chartData} />
                </div>
                <div className="bg-white p-6 rounded-xl shadow-lg">
                    <h3 className="text-lg font-semibold mb-4">Volume by Lane</h3>
                    <Bar options={{ responsive: true }} data={laneData} />
                </div>
            </div>
        </div>
    );
};
