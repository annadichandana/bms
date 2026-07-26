import React from 'react';
import { Building2, DoorOpen, Server, Users, Lightbulb, Zap, ThermometerSnowflake, Flame, Leaf, PowerOff } from 'lucide-react';

export function ZoneCard({ zoneName, zone, onControl }) {
  if (!zone) return null;

  const getIcon = () => {
    if (zoneName === 'office') return <Building2 size={24} />;
    if (zoneName === 'lobby') return <DoorOpen size={24} />;
    if (zoneName === 'server_room') return <Server size={24} />;
    return <Building2 size={24} />;
  };

  const getTempColor = (temp) => {
    if (temp < 21) return '#00d4ff'; // cool
    if (temp <= 24) return '#10b981'; // ideal
    return '#f59e0b'; // warm
  };
  
  const tempColor = getTempColor(zone.temperature);
  const isComfortable = zone.temperature >= 21 && zone.temperature <= 24 && zone.co2_ppm < 800;
  const isCritical = zone.temperature > 26 || zone.co2_ppm > 1000;
  
  let statusClass = 'status-ok';
  if (isCritical) statusClass = 'status-critical';
  else if (!isComfortable) statusClass = 'status-warning';

  const formatName = (name) => name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

  const hvacIcons = {
    'cooling': <ThermometerSnowflake size={16} className="text-[#00d4ff]" />,
    'heating': <Flame size={16} className="text-[#ef4444]" />,
    'eco': <Leaf size={16} className="text-[#10b981]" />,
    'off': <PowerOff size={16} className="text-[#94a3b8]" />
  };

  return (
    <div className={`glass ${statusClass}`} style={{ 
      padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem',
      transition: 'transform 0.2s', cursor: 'default', ':hover': { transform: 'translateY(-2px)' }
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{ padding: '0.5rem', background: 'rgba(255,255,255,0.1)', borderRadius: '8px' }}>
            {getIcon()}
          </div>
          <h3 style={{ margin: 0, fontSize: '1.25rem' }}>{formatName(zoneName)}</h3>
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{ 
            width: '10px', height: '10px', borderRadius: '50%', 
            background: isCritical ? '#ef4444' : (isComfortable ? '#10b981' : '#f59e0b'),
            boxShadow: `0 0 8px ${isCritical ? '#ef4444' : (isComfortable ? '#10b981' : '#f59e0b')}`
          }} />
          <span className="font-number" style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
            {(zone.hvac_power_kw + zone.lighting_power_kw + zone.plug_load_kw).toFixed(1)} kW
          </span>
        </div>
      </div>

      {/* Main Stats Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        
        {/* Temp Gauge */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
          <svg viewBox="0 0 100 100" style={{ width: '100px', height: '100px', transform: 'rotate(-90deg)' }}>
            <circle cx="50" cy="50" r="45" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="8" />
            <circle cx="50" cy="50" r="45" fill="none" stroke={tempColor} strokeWidth="8" 
              strokeDasharray={`${(zone.temperature / 40) * 283} 283`}
              style={{ transition: 'stroke-dasharray 1s ease' }}
            />
          </svg>
          <div style={{ position: 'absolute', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <span className="font-number" style={{ fontSize: '1.75rem', fontWeight: 'bold' }}>{zone.temperature.toFixed(1)}°</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>SET: {zone.hvac_setpoint.toFixed(1)}°</span>
          </div>
        </div>

        {/* Other Stats */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', justifyContent: 'center' }}>
          
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '0.25rem', color: 'var(--text-muted)' }}>
              <span>Humidity</span>
              <span className="font-number">{zone.humidity}%</span>
            </div>
            <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px' }}>
              <div style={{ height: '100%', background: '#00d4ff', borderRadius: '2px', width: `${zone.humidity}%` }} />
            </div>
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '0.25rem', color: 'var(--text-muted)' }}>
              <span>CO₂</span>
              <span className="font-number" style={{ color: zone.co2_ppm > 800 ? '#f59e0b' : 'inherit' }}>{zone.co2_ppm} ppm</span>
            </div>
            <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px' }}>
              <div style={{ height: '100%', background: zone.co2_ppm > 800 ? '#f59e0b' : '#10b981', borderRadius: '2px', width: `${Math.min(zone.co2_ppm / 2000 * 100, 100)}%` }} />
            </div>
          </div>

        </div>
      </div>

      {/* Footer Info */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'auto', paddingTop: '0.75rem', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(0,0,0,0.2)', padding: '0.25rem 0.5rem', borderRadius: '4px' }}>
          <Users size={14} className="text-[#94a3b8]" />
          <span className="font-number" style={{ fontSize: '0.875rem' }}>{zone.occupancy}/{zone.max_occupancy}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(0,0,0,0.2)', padding: '0.25rem 0.5rem', borderRadius: '4px', textTransform: 'uppercase', fontSize: '0.75rem', fontWeight: 'bold' }}>
          {hvacIcons[zone.hvac_mode] || <PowerOff size={14} />}
          <span>{zone.hvac_mode}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(0,0,0,0.2)', padding: '0.25rem 0.5rem', borderRadius: '4px' }}>
          <Lightbulb size={14} className={zone.lighting_level > 0 ? "text-[#f59e0b]" : "text-[#94a3b8]"} />
          <span className="font-number" style={{ fontSize: '0.875rem' }}>{zone.lighting_level}%</span>
        </div>

      </div>
    </div>
  );
}
