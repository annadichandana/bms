import React, { useState } from 'react';
import { Play, Square, RotateCcw, AlertTriangle, Settings2 } from 'lucide-react';

export function ControlPanel({ simState, onControl }) {
  const [selectedZone, setSelectedZone] = useState('office');
  const [setpoint, setSetpoint] = useState(22.0);
  const [mode, setMode] = useState('cooling');
  const [lightLevel, setLightLevel] = useState(80);

  const handleApply = () => {
    onControl('hvac-mode', { zone_id: selectedZone, mode });
    onControl('hvac-setpoint', { zone_id: selectedZone, setpoint });
    onControl('lighting', { zone_id: selectedZone, level: lightLevel });
  };

  const btnStyle = {
    background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
    color: 'white', padding: '0.5rem', borderRadius: '4px', cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem'
  };

  const activeBtnStyle = (color) => ({
    ...btnStyle, background: `rgba(${color}, 0.2)`, border: `1px solid rgba(${color}, 0.5)`, color: `rgb(${color})`
  });

  return (
    <div className="glass" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1.25rem', height: '100%' }}>
      <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem', textTransform: 'uppercase' }}>
        <Settings2 size={18} className="text-[#00d4ff]" /> Mission Control
      </h3>

      {/* Sim Controls */}
      <div style={{ background: 'rgba(0,0,0,0.2)', padding: '1rem', borderRadius: '8px' }}>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.75rem', textTransform: 'uppercase' }}>Simulation Engine</div>
        
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem', marginBottom: '1rem' }}>
          <button 
            onClick={() => onControl('simulation/start', {})}
            style={simState?.running ? activeBtnStyle('16, 185, 129') : btnStyle}
          >
            <Play size={14} /> Start
          </button>
          <button 
            onClick={() => onControl('simulation/stop', {})}
            style={!simState?.running ? activeBtnStyle('239, 68, 68') : btnStyle}
          >
            <Square size={14} /> Stop
          </button>
          <button onClick={() => onControl('simulation/reset', {})} style={btnStyle}>
            <RotateCcw size={14} /> Reset
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Speed</span>
          <input 
            type="range" min="1" max="100" 
            value={simState?.speed_multiplier || 10} 
            onChange={(e) => onControl('simulation/speed', { multiplier: parseInt(e.target.value) })}
            style={{ flex: 1, accentColor: '#00d4ff' }}
          />
          <span className="font-number" style={{ fontSize: '0.875rem' }}>{simState?.speed_multiplier || 1}x</span>
        </div>
      </div>

      {/* Manual Override */}
      <div style={{ background: 'rgba(0,0,0,0.2)', padding: '1rem', borderRadius: '8px', flex: 1 }}>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.75rem', textTransform: 'uppercase' }}>Manual Override</div>
        
        <select 
          value={selectedZone} onChange={(e) => setSelectedZone(e.target.value)}
          style={{ width: '100%', background: 'rgba(0,0,0,0.3)', color: 'white', border: '1px solid rgba(255,255,255,0.1)', padding: '0.5rem', borderRadius: '4px', marginBottom: '1rem', outline: 'none' }}
        >
          <option value="office">Office Area</option>
          <option value="lobby">Main Lobby</option>
          <option value="server_room">Server Room</option>
        </select>

        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
          {['cooling', 'heating', 'eco', 'off'].map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              ...btnStyle, flex: 1, fontSize: '0.75rem', textTransform: 'capitalize',
              ...(mode === m ? activeBtnStyle(m === 'cooling' ? '0, 212, 255' : m==='heating' ? '239, 68, 68' : m==='eco' ? '16, 185, 129' : '148, 163, 184') : {})
            }}>
              {m}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Setpoint</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button onClick={() => setSetpoint(s => s - 0.5)} style={{...btnStyle, padding: '0.25rem 0.5rem'}}>-</button>
            <span className="font-number" style={{ width: '40px', textAlign: 'center' }}>{setpoint.toFixed(1)}°</span>
            <button onClick={() => setSetpoint(s => s + 0.5)} style={{...btnStyle, padding: '0.25rem 0.5rem'}}>+</button>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Lights</span>
          <input 
            type="range" min="0" max="100" value={lightLevel} onChange={(e) => setLightLevel(parseInt(e.target.value))}
            style={{ flex: 1, accentColor: '#f59e0b' }}
          />
        </div>

        <button onClick={handleApply} style={{ width: '100%', background: '#7c3aed', color: 'white', border: 'none', padding: '0.75rem', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}>
          Apply Override
        </button>
      </div>

      <button 
        onClick={() => {
          if(confirm('Initiate Emergency Demand Response? This will drastically reduce power consumption.')) {
            onControl('demand-response', {});
          }
        }}
        style={{ width: '100%', background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.5)', padding: '0.75rem', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}
      >
        <AlertTriangle size={16} /> DEMAND RESPONSE
      </button>

    </div>
  );
}
