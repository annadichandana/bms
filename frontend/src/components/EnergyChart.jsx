import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';

export function EnergyChart({ energyHistory = [] }) {
  
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const opt = payload[0].value;
      const base = payload[1]?.value;
      const savings = base - opt;
      
      return (
        <div className="glass" style={{ padding: '0.75rem', border: '1px solid rgba(0, 212, 255, 0.3)' }}>
          <p style={{ margin: '0 0 0.5rem 0', color: 'var(--text-muted)', fontSize: '0.875rem' }}>Time: {label}</p>
          <p style={{ margin: 0, color: '#00d4ff', fontWeight: 'bold', fontSize: '0.875rem' }}>Optimized: {opt.toFixed(1)} kWh</p>
          {base && <p style={{ margin: 0, color: '#ef4444', fontSize: '0.875rem' }}>Baseline: {base.toFixed(1)} kWh</p>}
          {base && <p style={{ margin: '0.5rem 0 0 0', color: '#10b981', fontWeight: 'bold', fontSize: '0.875rem', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '0.25rem' }}>
            Savings: {savings.toFixed(1)} kWh
          </p>}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="glass" style={{ width: '100%', height: '100%', padding: '1.25rem', display: 'flex', flexDirection: 'column' }}>
      <h3 style={{ margin: '0 0 1rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <div style={{ width: '8px', height: '8px', background: '#00d4ff', borderRadius: '50%' }} />
        Real-Time Energy Consumption vs Baseline
      </h3>
      
      <div style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={energyHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="colorOpt" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00d4ff" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#00d4ff" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" vertical={false} />
            <XAxis dataKey="time" stroke="rgba(255,255,255,0.3)" tick={{fill: 'rgba(255,255,255,0.5)', fontSize: 12}} />
            <YAxis stroke="rgba(255,255,255,0.3)" tick={{fill: 'rgba(255,255,255,0.5)', fontSize: 12}} />
            <Tooltip content={<CustomTooltip />} />
            
            {/* Baseline */}
            <Area 
              type="monotone" 
              dataKey="baseline" 
              stroke="#ef4444" 
              strokeDasharray="5 5"
              fill="none"
              strokeWidth={2}
              isAnimationActive={false}
            />
            
            {/* Optimized */}
            <Area 
              type="monotone" 
              dataKey="optimized" 
              stroke="#00d4ff" 
              fillOpacity={1} 
              fill="url(#colorOpt)" 
              strokeWidth={2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
