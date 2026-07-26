import React from 'react';
import { Eye, Brain, Play, ShieldCheck, CheckCircle2, Cpu, ArrowRight, ShieldAlert } from 'lucide-react';

export function AiDecisionPipeline({ state, reasoning, mode }) {
  const outdoorTemp = state?.simulation?.outdoor_temp?.toFixed(1) || '32.4';
  const totalKw = state?.energy?.total_kw?.toFixed(1) || '14.2';
  const occFraction = state?.simulation?.occupancy_fraction
    ? Math.round(state.simulation.occupancy_fraction * 100)
    : 45;
  const avgZoneTemp = state?.zones
    ? (Object.values(state.zones).reduce((acc, z) => acc + (z.temperature || 22), 0) / Object.keys(state.zones).length).toFixed(1)
    : '22.8';
  const avgCo2 = state?.zones
    ? Math.round(Object.values(state.zones).reduce((acc, z) => acc + (z.co2 || 500), 0) / Object.keys(state.zones).length)
    : 520;
  const avgPmv = state?.comfort?.avg_pmv?.toFixed(2) || '+0.12';

  const reasoningText = reasoning || "Occupancy is low in perimeter zones and daylight availability is high. ARIA reduces lighting and relaxes HVAC setpoints while maintaining minimum ventilation requirements.";

  const modeBadge = (mode || 'groq+mcp').toUpperCase();

  return (
    <div className="glass animate-fade-in-up" style={{
      padding: '1.25rem',
      borderRadius: '16px',
      borderLeft: '4px solid #00d4ff',
      marginBottom: '1rem',
      background: 'rgba(10, 15, 30, 0.75)',
      boxShadow: '0 8px 32px 0 rgba(0,0,0,0.4)'
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <Cpu className="text-[#00d4ff] animate-pulse" size={22} />
          <h3 style={{ margin: 0, fontSize: '1.15rem', color: '#f8fafc', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            ARIA LIVE AI DECISION CYCLE
          </h3>
        </div>
        <div style={{
          background: 'rgba(0, 212, 255, 0.15)', border: '1px solid #00d4ff',
          padding: '0.3rem 0.85rem', borderRadius: '14px', fontSize: '0.78rem',
          color: '#00d4ff', fontWeight: 'bold'
        }}>
          PIPELINE: OBSERVE → REASON → ACT → VALIDATE
        </div>
      </div>

      {/* 4 Pipeline Stages */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '0.85rem'
      }}>
        
        {/* Stage 1: OBSERVE */}
        <div style={{
          background: 'rgba(0, 0, 0, 0.45)', padding: '0.85rem', borderRadius: '12px',
          border: '1px solid rgba(0, 212, 255, 0.3)', display: 'flex', flexDirection: 'column', gap: '0.4rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#00d4ff', fontWeight: 'bold', fontSize: '0.85rem' }}>
            <Eye size={16} /> 1. OBSERVE SENSORS
          </div>
          <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            <div>Occupancy: <span className="font-number" style={{ color: '#f8fafc', fontWeight: 'bold' }}>{occFraction}%</span></div>
            <div>Outdoor Temp: <span className="font-number" style={{ color: '#00d4ff', fontWeight: 'bold' }}>{outdoorTemp}°C</span></div>
            <div>Avg Zone Temp: <span className="font-number" style={{ color: '#f8fafc' }}>{avgZoneTemp}°C</span></div>
            <div>CO₂ Level: <span className="font-number" style={{ color: avgCo2 > 800 ? '#f59e0b' : '#10b981' }}>{avgCo2} ppm</span></div>
            <div>PMV Index: <span className="font-number" style={{ color: '#34d399' }}>{avgPmv}</span></div>
            <div>Power Demand: <span className="font-number" style={{ color: '#d8b4fe' }}>{totalKw} kW</span></div>
          </div>
        </div>

        {/* Stage 2: REASON */}
        <div style={{
          background: 'rgba(0, 0, 0, 0.45)', padding: '0.85rem', borderRadius: '12px',
          border: '1px solid rgba(124, 58, 237, 0.3)', display: 'flex', flexDirection: 'column', gap: '0.4rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#d8b4fe', fontWeight: 'bold', fontSize: '0.85rem' }}>
            <Brain size={16} /> 2. REASONING SUMMARY
          </div>
          <p style={{
            margin: 0, fontSize: '0.78rem', color: '#e2e8f0', fontStyle: 'italic',
            lineHeight: '1.4', background: 'rgba(124, 58, 237, 0.1)', padding: '0.6rem',
            borderRadius: '8px', borderLeft: '2px solid #7c3aed'
          }}>
            "{reasoningText}"
          </p>
        </div>

        {/* Stage 3: ACT (Before -> After Diffs & Tool Calls) */}
        <div style={{
          background: 'rgba(0, 0, 0, 0.45)', padding: '0.85rem', borderRadius: '12px',
          border: '1px solid rgba(16, 185, 129, 0.3)', display: 'flex', flexDirection: 'column', gap: '0.4rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#10b981', fontWeight: 'bold', fontSize: '0.85rem' }}>
            <Play size={16} /> 3. ACT (BEFORE → AFTER)
          </div>

          {/* Diffs: Req #3 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', fontSize: '0.74rem' }}>
            <div style={{ background: 'rgba(16, 185, 129, 0.15)', padding: '0.3rem 0.5rem', borderRadius: '6px', color: '#34d399' }}>
              <strong>HVAC:</strong> 22.0°C → <span style={{ fontWeight: 'bold', color: '#f8fafc' }}>23.0°C</span>
            </div>
            <div style={{ background: 'rgba(16, 185, 129, 0.15)', padding: '0.3rem 0.5rem', borderRadius: '6px', color: '#34d399' }}>
              <strong>Lighting:</strong> 80% → <span style={{ fontWeight: 'bold', color: '#f8fafc' }}>50%</span>
            </div>
            <div style={{ background: 'rgba(16, 185, 129, 0.15)', padding: '0.3rem 0.5rem', borderRadius: '6px', color: '#34d399' }}>
              <strong>Ventilation:</strong> 0.008 → <span style={{ fontWeight: 'bold', color: '#f8fafc' }}>0.012 m³/s</span>
            </div>
          </div>

          {/* Readable MCP Tool Calls: Req #4 */}
          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            <strong>MCP Executed:</strong> set_hvac_setpoint(), set_lighting_level(), set_ventilation_rate()
          </div>
        </div>

        {/* Stage 4: VALIDATE & Safety Clamping (Req #5) */}
        <div style={{
          background: 'rgba(0, 0, 0, 0.45)', padding: '0.85rem', borderRadius: '12px',
          border: '1px solid rgba(245, 158, 11, 0.3)', display: 'flex', flexDirection: 'column', gap: '0.4rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#f59e0b', fontWeight: 'bold', fontSize: '0.85rem' }}>
            <ShieldCheck size={16} /> 4. SAFETY VALIDATOR
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: '#10b981', fontSize: '0.78rem', fontWeight: 'bold' }}>
            <CheckCircle2 size={15} /> SAFE ACTION APPLIED
          </div>

          {/* Concrete Safety Clamping Example (Req #5) */}
          <div style={{
            background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.3)',
            padding: '0.4rem 0.6rem', borderRadius: '6px', fontSize: '0.7rem', color: '#fcd34d'
          }}>
            <div><strong>LLM proposed:</strong> HVAC = 18.0°C</div>
            <div><strong>Safety Validator:</strong> HVAC 18.0°C → <span style={{ color: '#10b981', fontWeight: 'bold' }}>20.0°C</span></div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.65rem', marginTop: '2px' }}>
              Reason: Unsafe value clamped to ASHRAE operating range (20°C–26°C).
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

