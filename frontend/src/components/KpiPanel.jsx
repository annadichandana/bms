import React from 'react';
import { Leaf, Coins, Zap, Thermometer, Clock } from 'lucide-react';

export function KpiPanel({ energy, simulation, comfortScore = 92 }) {
  if (!energy || !simulation) return null;

  const kpis = [
    {
      label: 'Energy Saved',
      value: `${energy.savings_pct?.toFixed(1)}%`,
      icon: <Zap size={24} className="text-[#10b981]" />,
      color: 'rgba(16, 185, 129, 0.2)',
      border: 'rgba(16, 185, 129, 0.5)'
    },
    {
      label: 'CO₂ Reduced',
      value: `${energy.carbon_kg?.toFixed(1)} kg`,
      icon: <Leaf size={24} className="text-[#10b981]" />,
      color: 'rgba(16, 185, 129, 0.2)',
      border: 'rgba(16, 185, 129, 0.5)'
    },
    {
      label: 'Cost Savings',
      value: `$${energy.savings_usd?.toFixed(2)}`,
      icon: <Coins size={24} className="text-[#f59e0b]" />,
      color: 'rgba(245, 158, 11, 0.2)',
      border: 'rgba(245, 158, 11, 0.5)'
    },
    {
      label: 'Comfort Score',
      value: `${comfortScore}/100`,
      icon: <Thermometer size={24} className="text-[#00d4ff]" />,
      color: 'rgba(0, 212, 255, 0.2)',
      border: 'rgba(0, 212, 255, 0.5)'
    },
    {
      label: 'Outdoor Temp',
      value: `${simulation.outdoor_temp?.toFixed(1)}°C`,
      icon: <Thermometer size={24} className="text-[#94a3b8]" />,
      color: 'rgba(148, 163, 184, 0.2)',
      border: 'rgba(148, 163, 184, 0.5)'
    }
  ];

  const formatSimTime = (isoString) => {
    if (!isoString) return '--:--';
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div style={{ display: 'flex', gap: '1rem', width: '100%', marginBottom: '1rem', overflowX: 'auto', paddingBottom: '0.5rem' }}>
      
      <div className="glass" style={{
        display: 'flex', alignItems: 'center', gap: '1rem', padding: '1rem 1.5rem',
        borderLeft: '4px solid #7c3aed', flexShrink: 0
      }}>
        <Clock size={28} className="text-[#7c3aed]" />
        <div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sim Time</div>
          <div className="font-number" style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>
            {formatSimTime(simulation.sim_time)}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--primary)', marginTop: '0.25rem' }}>
            {simulation.speed_multiplier}x Speed {simulation.running ? '(Running)' : '(Paused)'}
          </div>
        </div>
      </div>

      {kpis.map((kpi, idx) => (
        <div key={idx} className="glass" style={{
          display: 'flex', alignItems: 'center', gap: '1rem', padding: '1rem 1.5rem', flex: 1, minWidth: '180px',
          borderTop: `1px solid ${kpi.border}`, transition: 'all 0.3s ease'
        }}>
          <div style={{ 
            width: '48px', height: '48px', borderRadius: '50%', backgroundColor: kpi.color,
            display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}>
            {kpi.icon}
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{kpi.label}</div>
            <div className="font-number" style={{ fontSize: '1.5rem', fontWeight: 'bold', transition: 'all 0.3s ease' }}>
              {kpi.value}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
