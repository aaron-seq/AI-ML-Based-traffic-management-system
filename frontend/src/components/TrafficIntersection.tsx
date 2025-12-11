import React from 'react';
import { motion } from 'framer-motion';

interface TrafficIntersectionProps {
    status: any;
    isSimulationRunning: boolean;
}

export const TrafficIntersection: React.FC<TrafficIntersectionProps> = ({ status, isSimulationRunning }) => {
    // Mock data if status is null (visual placeholder)
    const signals = status?.traffic_signals || {
        north: { current_state: 'red', remaining_time: 30 },
        south: { current_state: 'red', remaining_time: 30 },
        east: { current_state: 'green', remaining_time: 15 },
        west: { current_state: 'green', remaining_time: 15 },
    };

    const getSignalColor = (state: string) => {
        switch (state) {
            case 'red': return 'bg-red-500 shadow-red-500/50';
            case 'yellow': return 'bg-yellow-400 shadow-yellow-400/50';
            case 'green': return 'bg-green-500 shadow-green-500/50';
            default: return 'bg-gray-700';
        }
    };

    return (
        <div className="relative w-full aspect-square bg-gray-900 rounded-lg overflow-hidden border-4 border-gray-700">
            {/* Intersection Roads */}
            <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-24 h-full bg-gray-600 border-l-2 border-r-2 border-dashed border-gray-400"></div>
                <div className="absolute w-full h-24 bg-gray-600 border-t-2 border-b-2 border-dashed border-gray-400"></div>
            </div>

            {/* Center Intersection */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="w-24 h-24 bg-gray-700 z-10"></div>
            </div>

            {/* Traffic Signals */}
            {/* North */}
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20">
                <TrafficLight
                    direction="North"
                    color={getSignalColor(signals.north.current_state)}
                    time={signals.north.remaining_time}
                />
            </div>

            {/* South */}
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20">
                <TrafficLight
                    direction="South"
                    color={getSignalColor(signals.south.current_state)}
                    time={signals.south.remaining_time}
                />
            </div>

            {/* East */}
            <div className="absolute right-4 top-1/2 -translate-y-1/2 z-20">
                <TrafficLight
                    direction="East"
                    color={getSignalColor(signals.east.current_state)}
                    time={signals.east.remaining_time}
                    horizontal
                />
            </div>

            {/* West */}
            <div className="absolute left-4 top-1/2 -translate-y-1/2 z-20">
                <TrafficLight
                    direction="West"
                    color={getSignalColor(signals.west.current_state)}
                    time={signals.west.remaining_time}
                    horizontal
                />
            </div>

            {!isSimulationRunning && !status && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-30">
                    <p className="text-white font-semibold">Simulation Stopped</p>
                </div>
            )}
        </div>
    );
};

interface TrafficLightProps {
    direction: string;
    color: string;
    time: number;
    horizontal?: boolean;
}

const TrafficLight: React.FC<TrafficLightProps> = ({ direction, color, time, horizontal }) => (
    <div className={`bg-black p-2 rounded-lg border border-gray-600 flex ${horizontal ? 'flex-row space-x-2' : 'flex-col space-y-2'} items-center`}>
        <motion.div
            animate={{ opacity: [0.8, 1, 0.8] }}
            transition={{ duration: 2, repeat: Infinity }}
            className={`w-4 h-4 rounded-full shadow-lg ${color}`}
        />
        <span className="text-xs text-white font-mono">{time}s</span>
    </div>
);
