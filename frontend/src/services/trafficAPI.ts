import axios from 'axios';

const api = axios.create({
    baseURL: '/api', // Proxied by Vite to localhost:8000
    headers: {
        'Content-Type': 'application/json',
    },
});

export const TrafficAPI = {
    detectVehicles: async (formData: FormData) => {
        try {
            const response = await api.post('/detect-vehicles', formData, {
                headers: {
                    'Content-Type': 'multipart/form-data',
                },
            });
            return response.data;
        } catch (error) {
            console.error('Error detecting vehicles:', error);
            throw error;
        }
    },

    getSystemInfo: async () => {
        try {
            const response = await api.get('/system/info');
            return response.data;
        } catch (error) {
            console.error('Error fetching system info:', error);
            throw error;
        }
    },

    startSimulation: async () => {
        // Mock for now, or implement backend endpoint
        console.log("Starting simulation...");
        return { status: "started" };
    },

    getAnalytics: async (period = "current") => {
        try {
            const response = await api.get(`/analytics/summary?period=${period}`);
            return response.data;
        } catch (error) {
            console.error('Error fetching analytics:', error);
            // Fallback for demo if backend analytics fails
            return {
                total_vehicles_today: 0,
                average_wait_time: 0,
                efficiency: 0
            };
        }
    }
};
