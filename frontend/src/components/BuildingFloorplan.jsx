import React from 'react';

export function BuildingFloorplan({ zones }) {
  if (!zones) return <div className="glass" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>Loading Plan...</div>;

  const getTempColor = (temp) => {
    if (temp < 20) return 'rgba(0, 212, 255, 0.3)';
    if (temp <= 24) return 'rgba(16, 185, 129, 0.3)';
    if (temp <= 26) return 'rgba(245, 158, 11, 0.3)';
    return 'rgba(239, 68, 68, 0.4)';
  };

  const getStrokeColor = (temp) => {
    if (temp < 20) return '#00d4ff';
    if (temp <= 24) return '#10b981';
    if (temp <= 26) return '#f59e0b';
    return '#ef4444';
  };

  return (
    <div className="glass" style={{ height: '250px', padding: '1rem', position: 'relative', overflow: 'hidden' }}>
      <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.875rem', color: 'var(--text-muted)' }}>Floor Plan Thermal Map</h3>
      
      <svg width="100%" height="100%" viewBox="0 0 400 200" style={{ filter: 'drop-shadow(0 0 10px rgba(0,0,0,0.5))' }}>
        {/* Background outline */}
        <rect x="10" y="10" width="380" height="180" fill="rgba(0,0,0,0.5)" stroke="rgba(255,255,255,0.1)" strokeWidth="2" rx="4" />
        
        {/* Office */}
        <g style={{ transition: 'all 0.5s ease' }}>
          <rect x="20" y="20" width="180" height="160" 
            fill={getTempColor(zones.office?.temperature || 22)} 
            stroke={getStrokeColor(zones.office?.temperature || 22)} strokeWidth="2" rx="2" 
          />
          <text x="110" y="90" fill="white" fontSize="14" fontWeight="bold" textAnchor="middle">OFFICE</text>
          <text x="110" y="110" fill="white" fontSize="16" fontFamily="Rajdhani" textAnchor="middle">{zones.office?.temperature?.toFixed(1)}°C</text>
        </g>

        {/* Lobby */}
        <g style={{ transition: 'all 0.5s ease' }}>
          <rect x="210" y="20" width="100" height="160" 
            fill={getTempColor(zones.lobby?.temperature || 22)} 
            stroke={getStrokeColor(zones.lobby?.temperature || 22)} strokeWidth="2" rx="2" 
          />
          <text x="260" y="90" fill="white" fontSize="14" fontWeight="bold" textAnchor="middle">LOBBY</text>
          <text x="260" y="110" fill="white" fontSize="16" fontFamily="Rajdhani" textAnchor="middle">{zones.lobby?.temperature?.toFixed(1)}°C</text>
        </g>

        {/* Server Room */}
        <g style={{ transition: 'all 0.5s ease' }}>
          <rect x="320" y="20" width="60" height="100" 
            fill={getTempColor(zones.server_room?.temperature || 19)} 
            stroke={getStrokeColor(zones.server_room?.temperature || 19)} strokeWidth="2" rx="2" 
          />
          <text x="350" y="60" fill="white" fontSize="10" fontWeight="bold" textAnchor="middle">SERVER</text>
          <text x="350" y="80" fill="white" fontSize="14" fontFamily="Rajdhani" textAnchor="middle">{zones.server_room?.temperature?.toFixed(1)}°C</text>
          
          {/* Heat warning animation if hot */}
          {zones.server_room?.temperature > 24 && (
            <circle cx="350" cy="50" r="20" fill="none" stroke="#ef4444" strokeWidth="2">
              <animate attributeName="r" values="20; 40" dur="1s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="1; 0" dur="1s" repeatCount="indefinite" />
            </circle>
          )}
        </g>

        {/* Scan line effect overlay */}
        <line x1="10" y1="10" x2="10" y2="190" stroke="rgba(0, 212, 255, 0.5)" strokeWidth="2">
          <animate attributeName="x1" values="10; 390; 10" dur="4s" repeatCount="indefinite" />
          <animate attributeName="x2" values="10; 390; 10" dur="4s" repeatCount="indefinite" />
        </line>
      </svg>
    </div>
  );
}
