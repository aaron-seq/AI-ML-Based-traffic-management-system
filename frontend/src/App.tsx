import { useState, useEffect } from 'react';
import { Toaster } from 'react-hot-toast';
import { TrafficDashboard } from './components/TrafficDashboard';

/**
 * Main Application Component
 *
 * Rationale: Serves as the root component that sets up global providers
 * and renders the main dashboard. Kept simple to allow easy extension.
 */
function App() {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Initial health check to verify backend connectivity
    const checkBackendHealth = async () => {
      try {
        const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
        const response = await fetch(`${apiUrl}/health`);
        if (!response.ok) {
          throw new Error('Backend service unavailable');
        }
        setIsLoading(false);
      } catch (err) {
        console.error('Backend health check failed:', err);
        // Still show dashboard but with degraded state
        setError('Backend connection failed. Some features may be unavailable.');
        setIsLoading(false);
      }
    };

    checkBackendHealth();
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <p className="text-white text-lg">Connecting to Traffic Management System...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900">
      {/* Toast notifications */}
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            background: '#1f2937',
            color: '#fff',
            border: '1px solid #374151',
          },
          success: {
            iconTheme: {
              primary: '#10b981',
              secondary: '#fff',
            },
          },
          error: {
            iconTheme: {
              primary: '#ef4444',
              secondary: '#fff',
            },
          },
        }}
      />

      {/* Connection warning banner */}
      {error && (
        <div className="bg-yellow-600 text-white px-4 py-2 text-center text-sm">
          {error}
        </div>
      )}

      {/* Main dashboard */}
      <TrafficDashboard />
    </div>
  );
}

export default App;
