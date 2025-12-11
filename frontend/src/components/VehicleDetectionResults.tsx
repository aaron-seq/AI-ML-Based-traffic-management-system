import React from 'react';

interface VehicleDetectionResultsProps {
    results: any;
}

export const VehicleDetectionResults: React.FC<VehicleDetectionResultsProps> = ({ results }) => {
    if (!results) return null;

    return (
        <div className="bg-white rounded-xl shadow-lg p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Detection Results</h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Annotated Image */}
                <div className="relative rounded-lg overflow-hidden border">
                    {/* In a real app, this would be the URL returned by the backend. 
               For now, we might need to handle serving the static file from backend */}
                    {results.annotated_image_path ? (
                        <img
                            src={`http://localhost:8000/static/${results.annotated_image_path}`}
                            alt="Detected Vehicles"
                            className="w-full h-auto object-contain"
                        />
                    ) : (
                        <div className="flex items-center justify-center h-64 bg-gray-100 text-gray-400">
                            No Image Available
                        </div>
                    )}
                </div>

                {/* Stats */}
                <div className="space-y-4">
                    <div className="p-4 bg-blue-50 rounded-lg">
                        <p className="text-sm text-blue-800">Total Vehicles</p>
                        <p className="text-3xl font-bold text-blue-600">{results.total_vehicles}</p>
                    </div>

                    <div>
                        <h4 className="font-medium text-gray-700 mb-2">Breakdown by Lane</h4>
                        <div className="grid grid-cols-2 gap-2">
                            {Object.entries(results.lane_counts || {}).map(([lane, count]) => (
                                <div key={lane} className="flex justify-between items-center p-2 bg-gray-50 rounded">
                                    <span className="capitalize text-gray-600">{lane}</span>
                                    <span className="font-bold text-gray-900">{count as number}</span>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="text-xs text-gray-400">
                        Processing Time: {(results.processing_time * 1000).toFixed(2)}ms
                    </div>
                </div>
            </div>
        </div>
    );
};
