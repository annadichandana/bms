import React, { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { KpiPanel } from './components/KpiPanel';
import { ZoneCard } from './components/ZoneCard';
import { EnergyChart } from './components/EnergyChart';
import { AiChatLog } from './components/AiChatLog';
import { ControlPanel } from './components/ControlPanel';
import { BuildingFloorplan } from './components/BuildingFloorplan';
import { ComparisonBanner } from './components/ComparisonBanner';
import { AiDecisionPipeline } from './components/AiDecisionPipeline';
import { ArchitecturePanel } from './components/ArchitecturePanel';
import { Wifi, WifiOff, LayoutDashboard, Cpu, Layers } from 'lucide-react';

function App() {
  const { state, isConnected } = useWebSocket('ws://localhost:8000/ws');
  const [energyHistory, setEnergyHistory] = useState([]);
  const [activeTab, setActiveTab] = useState('pipeline'); // 'pipeline' | 'architecture'

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
  }, [state?.simulation?.sim_time]);

  const handleControl = async (action, payload) => {
    try {
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

  const latestReasoning = state?.reasoning || (state?.ai_log && state.ai_log.length > 0 ? state.ai_log[state.ai_log.length - 1].reasoning : "");

  return (
    <div style={{ padding: '1.5rem', minHeight: '100vh', display: 'flex', flexDirection: 'column', gap: '1rem', position: 'relative' }}>
      
      {/* Header */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <h1 className="text-gradient" style={{ margin: 0, fontSize: '2.2rem' }}>ARIA BMS</h1>
          <div style={{ background: 'rgba(124, 58, 237, 0.2)', color: '#d8b4fe', padding: '0.25rem 0.75rem', borderRadius: '16px', fontSize: '0.75rem', fontWeight: 'bold', border: '1px solid rgba(124, 58, 237, 0.5)' }}>
            CLOSED-LOOP RESILIENT BMS
          </div>
        </div>

        {/* View Tabs */}
        <div style={{ display: 'flex', gap: '0.5rem', background: 'rgba(0,0,0,0.4)', padding: '0.25rem', borderRadius: '10px', border: '1px solid var(--border)' }}>
          <button
            onClick={() => setActiveTab('pipeline')}
            style={{
              background: activeTab === 'pipeline' ? '#7c3aed' : 'transparent',
              color: activeTab === 'pipeline' ? '#ffffff' : '#94a3b8',
              border: 'none', padding: '0.35rem 0.85rem', borderRadius: '8px',
              fontSize: '0.8rem', fontWeight: 'bold', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem',
              transition: 'all 0.2s ease'
            }}
          >
            <Cpu size={14} /> Decision Pipeline
          </button>
          <button
            onClick={() => setActiveTab('architecture')}
            style={{
              background: activeTab === 'architecture' ? '#7c3aed' : 'transparent',
              color: activeTab === 'architecture' ? '#ffffff' : '#94a3b8',
              border: 'none', padding: '0.35rem 0.85rem', borderRadius: '8px',
              fontSize: '0.8rem', fontWeight: 'bold', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem',
              transition: 'all 0.2s ease'
            }}
          >
            <Layers size={14} /> Safety Architecture
          </button>
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
          background: 'rgba(10, 15, 30, 0.85)', backdropFilter: 'blur(6px)',
          zIndex: 50, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
        }}>
          <WifiOff size={48} className="text-[#ef4444] animate-pulse" style={{ marginBottom: '1rem' }} />
          <h2 style={{ color: 'white', margin: 0 }}>Connection to ARIA Server Lost</h2>
          <p style={{ color: 'var(--text-muted)' }}>Attempting to reconnect...</p>
        </div>
      )}

      {/* Main Layout */}
      {state ? (
        <>
          {/* 1. Large Baseline vs AI Comparison Banner */}
          <ComparisonBanner energy={state.energy} summary={state.summary} />

          {/* 2. KPI Summary Bar */}
          <KpiPanel energy={state.energy} simulation={state.simulation} />

          {/* 3. Interactive Decision Pipeline or Architecture View */}
          {activeTab === 'pipeline' ? (
            <AiDecisionPipeline state={state} reasoning={latestReasoning} mode={state.mode} />
          ) : (
            <ArchitecturePanel />
          )}
          
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr 1fr', gap: '1rem', flex: 1, minHeight: 0 }}>
            
            {/* Left Column: Floorplan & Control */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <BuildingFloorplan zones={state.zones} />
              <div style={{ flex: 1 }}>
                <ControlPanel simState={state.simulation} onControl={handleControl} />
              </div>
            </div>

            {/* Center Column: Zones */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', overflowY: 'auto', paddingRight: '0.5rem', maxHeight: '550px' }}>
              {Object.entries(state.zones).map(([key, zone]) => (
                <ZoneCard key={key} zoneName={key} zone={zone} onControl={handleControl} />
              ))}
            </div>

            {/* Right Column: AI Intelligence Log */}
            <div style={{ height: '100%', maxHeight: '550px' }}>
              <AiChatLog aiLog={state.ai_log} />
            </div>

          </div>

          {/* Bottom Energy Chart */}
          <div style={{ height: '220px', marginTop: '0.5rem' }}>
            <EnergyChart energyHistory={energyHistory} />
          </div>
        </>
      ) : (
        isConnected && <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>Initializing ARIA system state...</div>
      )}

      {/* Footer / Watermark */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', opacity: 0.4, fontSize: '0.75rem', marginTop: '1rem' }}>
        <div>ARIA Autonomous Building Management System v2.0</div>
        <div>HONEYWELL HACKATHON 2024</div>
      </div>

    </div>
  );
}

export default App;

