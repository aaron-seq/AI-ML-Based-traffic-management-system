import { Toaster } from 'react-hot-toast';
import { TrafficDashboard } from './components/TrafficDashboard';

function App() {
    return (
        <>
            <TrafficDashboard />
            <Toaster position="top-right" />
        </>
    );
}

export default App;
