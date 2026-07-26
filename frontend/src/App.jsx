import React, { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { KpiPanel } from './components/KpiPanel';
import { ZoneCard } from './components/ZoneCard';
import { EnergyChart } from './components/EnergyChart';
import { AiChatLog } from './components/AiChatLog';
import { ControlPanel } from './components/ControlPanel';
import { BuildingFloorplan } from './components/BuildingFloorplan';
import { Wifi, WifiOff } from 'lucide-react';

function App() {
  const { state, isConnected } = useWebSocket('ws://localhost:8000/ws');
  const [energyHistory, setEnergyHistory] = useState([]);

  useEffect(() => {
    if (state?.energy && state?.simulation) {
      const timeStr = new Date(state.simulation.sim_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      
      setEnergyHistory(prev => {
        const newData = [...prev, {
          time: timeStr,
          optimized: state.energy.total_kwh,
          baseline: state.energy.baseline_kwh
        }];
        if (newData.length > 60) return newData.slice(newData.length - 60);
        return newData;
      });
    }
  }, [state?.simulation?.sim_time]); // Dependency on sim_time ensures we update per tick

  const handleControl = async (action, payload) => {
    try {
      // Determine endpoint based on action
      let endpoint = `/api/control/${action}`;
      if (action.startsWith('simulation/')) {
        endpoint = `/api/${action}`;
      }

      await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (err) {
      console.error('Failed to send control command:', err);
    }
  };

  return (
    <div style={{ padding: '1.5rem', height: '100vh', display: 'flex', flexDirection: 'column', gap: '1rem', position: 'relative' }}>
      
      {/* Header */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <h1 className="text-gradient" style={{ margin: 0, fontSize: '2rem' }}>ARIA BMS</h1>
          <div style={{ background: 'rgba(124, 58, 237, 0.2)', color: '#d8b4fe', padding: '0.25rem 0.75rem', borderRadius: '16px', fontSize: '0.75rem', fontWeight: 'bold', border: '1px solid rgba(124, 58, 237, 0.5)' }}>
            POWERED BY LLaMA 3
          </div>
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: isConnected ? '#10b981' : '#ef4444', fontSize: '0.875rem' }}>
            {isConnected ? <Wifi size={16} /> : <WifiOff size={16} />}
            {isConnected ? 'SYSTEM ONLINE' : 'CONNECTION LOST'}
          </div>
        </div>
      </header>

      {/* Connection Overlay */}
      {!isConnected && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, 
          background: 'rgba(10, 15, 30, 0.8)', backdropFilter: 'blur(4px)',
          zIndex: 50, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
        }}>
          <WifiOff size={48} className="text-[#ef4444] animate-pulse" style={{ marginBottom: '1rem' }} />
          <h2 style={{ color: 'white', margin: 0 }}>Connection to Backend Lost</h2>
          <p style={{ color: 'var(--text-muted)' }}>Attempting to reconnect...</p>
        </div>
      )}

      {/* Main Layout */}
      {state ? (
        <>
          <KpiPanel energy={state.energy} simulation={state.simulation} />
          
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem', flex: 1, minHeight: 0 }}>
            
            {/* Left Column */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <BuildingFloorplan zones={state.zones} />
              <div style={{ flex: 1 }}>
                <ControlPanel simState={state.simulation} onControl={handleControl} />
              </div>
            </div>

            {/* Center Column: Zones */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', overflowY: 'auto', paddingRight: '0.5rem' }}>
              {Object.entries(state.zones).map(([key, zone]) => (
                <ZoneCard key={key} zoneName={key} zone={zone} onControl={handleControl} />
              ))}
            </div>

            {/* Right Column: AI Log */}
            <div style={{ height: '100%' }}>
              <AiChatLog aiLog={state.ai_log} />
            </div>

          </div>

          {/* Bottom Chart */}
          <div style={{ height: '220px' }}>
            <EnergyChart energyHistory={energyHistory} />
          </div>
        </>
      ) : (
        isConnected && <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>Initializing system state...</div>
      )}

      {/* Watermark */}
      <div style={{ position: 'fixed', bottom: '1rem', right: '1.5rem', opacity: 0.1, fontSize: '0.75rem', fontWeight: 'bold', pointerEvents: 'none' }}>
        HONEYWELL HACKATHON 2024
      </div>

    </div>
  );
}

export default App;
