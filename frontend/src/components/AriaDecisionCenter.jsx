import React, { useState } from 'react';
import {
  Eye, Brain, Play, ShieldCheck, TrendingUp,
  CheckCircle2, AlertTriangle, ChevronDown, ChevronUp,
  Cpu, Thermometer, Wind, Lightbulb, Zap, Activity
} from 'lucide-react';

/** Gradient pill badge */
function Badge({ children, color = '#00d4ff', bg }) {
  return (
    <span style={{
      background: bg || `${color}22`,
      border: `1px solid ${color}`,
      color,
      padding: '0.2rem 0.6rem',
      borderRadius: '10px',
      fontSize: '0.7rem',
      fontWeight: 'bold',
      letterSpacing: '0.04em',
    }}>{children}</span>
  );
}

/** Stage header pill */
function StageHeader({ icon: Icon, label, color, step }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
      <div style={{
        background: `${color}22`, border: `1px solid ${color}`,
        borderRadius: '8px', padding: '0.3rem',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Icon size={15} color={color} />
      </div>
      <span style={{ color, fontWeight: 'bold', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {step}. {label}
      </span>
    </div>
  );
}

/** Metric row inside OBSERVE */
function ObserveRow({ label, value, color = '#f8fafc', icon: Icon }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.74rem', padding: '0.18rem 0' }}>
      <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
        {Icon && <Icon size={11} />}{label}
      </span>
      <span style={{ color, fontWeight: 'bold', fontFamily: 'Rajdhani, monospace' }}>{value}</span>
    </div>
  );
}

/** ACT: before → applied arrow row */
function ActRow({ label, before, applied, unit, icon: Icon, color = '#10b981' }) {
  const changed = Math.abs((parseFloat(applied) || 0) - (parseFloat(before) || 0)) > 0.001;
  return (
    <div style={{
      background: 'rgba(0,0,0,0.3)', padding: '0.4rem 0.6rem', borderRadius: '8px',
      border: `1px solid ${changed ? color + '44' : 'rgba(255,255,255,0.06)'}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      fontSize: '0.74rem',
    }}>
      <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
        {Icon && <Icon size={12} />}{label}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontFamily: 'Rajdhani, monospace' }}>
        <span style={{ color: '#94a3b8', textDecoration: changed ? 'line-through' : 'none' }}>
          {typeof before === 'number' ? before.toFixed(unit === 'm³/s' ? 3 : 1) : before}{unit}
        </span>
        {changed && (
          <>
            <span style={{ color: '#475569' }}>→</span>
            <span style={{ color, fontWeight: 'bold' }}>
              {typeof applied === 'number' ? applied.toFixed(unit === 'm³/s' ? 3 : 1) : applied}{unit}
            </span>
          </>
        )}
        {!changed && <span style={{ color: '#64748b', fontSize: '0.65rem' }}>STABLE</span>}
      </div>
    </div>
  );
}

export function AriaDecisionCenter({ state }) {
  const [expanded, setExpanded] = useState(true);

  if (!state) return null;

  const dd       = state.decision_detail || {};
  const observe  = dd.observe  || {};
  const act      = dd.act      || {};
  const validate = dd.validate || {};
  const learn    = dd.learn    || {};
  const reasonText = dd.reason || state.reasoning || 'ARIA is analyzing building conditions...';

  // Controls for before→after
  const prevCtrl = state.prev_controls || {};
  const currCtrl = state.controls      || {};

  const prevHvac  = prevCtrl.hvac_setpoints   || {};
  const currHvac  = currCtrl.hvac_setpoints   || {};
  const prevLight = prevCtrl.lighting_levels  || {};
  const currLight = currCtrl.lighting_levels  || {};
  const prevVent  = prevCtrl.ventilation_rates || {};
  const currVent  = currCtrl.ventilation_rates || {};

  const avg = (obj) => {
    const vals = Object.values(obj || {}).filter(v => typeof v === 'number');
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  };

  // Observe data — prefer decision_detail.observe, fallback to normalized state
  const obs = {
    occupancy:    observe.occupancy_pct    ?? Math.round((state.simulation?.occupancy_fraction || 0) * 100),
    outdoorTemp:  observe.outdoor_temp_c   ?? state.simulation?.outdoor_temp ?? 30,
    avgZoneTemp:  observe.avg_zone_temp_c  ?? state.comfort?.avg_temp ?? 22,
    avgCo2:       observe.avg_co2_ppm      ?? state.comfort?.avg_co2  ?? 500,
    avgPmv:       observe.avg_pmv          ?? state.comfort?.avg_pmv  ?? 0,
    energyDemand: observe.energy_demand_kw ?? state.energy?.total_kw  ?? 0,
    co2Status:    observe.co2_status       ?? 'good',
    pmvStatus:    observe.pmv_status       ?? 'comfortable',
    carbonIntensity: observe.carbon_intensity ?? 'low',
  };

  // Safety events
  const safetyEvents  = state.safety_events || [];
  const hasClamping   = safetyEvents.length > 0;

  // Mode badge
  const modeLower = (state.mode || '').toLowerCase();
  const modeBadge = modeLower.includes('groq')
    ? { text: 'GROQ + MCP', color: '#10b981' }
    : modeLower.includes('ollama')
    ? { text: 'OLLAMA LOCAL', color: '#f59e0b' }
    : { text: 'STRATEGY + RULES', color: '#3b82f6' };

  const co2Color  = obs.avgCo2 > 900 ? '#ef4444' : obs.avgCo2 > 700 ? '#f59e0b' : '#10b981';
  const pmvColor  = Math.abs(obs.avgPmv) > 0.5 ? '#f59e0b' : '#34d399';
  const tempColor = obs.avgZoneTemp > 25 ? '#f59e0b' : obs.avgZoneTemp < 20 ? '#00d4ff' : '#34d399';

  return (
    <div style={{
      background: 'rgba(8, 12, 28, 0.9)',
      border: '1.5px solid rgba(0, 212, 255, 0.3)',
      borderRadius: '16px',
      marginBottom: '1rem',
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      overflow: 'hidden',
    }}>
      {/* ── Header ── */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          padding: '0.9rem 1.25rem',
          background: 'linear-gradient(135deg, rgba(0,212,255,0.08), rgba(124,58,237,0.08))',
          borderBottom: expanded ? '1px solid rgba(0,212,255,0.15)' : 'none',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          cursor: 'pointer', userSelect: 'none',
        }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Cpu size={20} color="#00d4ff" style={{ filter: 'drop-shadow(0 0 6px #00d4ff88)' }} />
          <span style={{ color: '#f8fafc', fontWeight: 'bold', fontSize: '1rem', letterSpacing: '0.05em' }}>
            ARIA AUTONOMOUS DECISION CENTER
          </span>
          <Badge color={modeBadge.color}>{modeBadge.text}</Badge>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{
            display: 'flex', gap: '0.3rem', alignItems: 'center',
            fontSize: '0.7rem', color: '#94a3b8',
          }}>
            {['OBSERVE', 'REASON', 'ACT', 'VALIDATE', 'LEARN'].map((s, i) => (
              <React.Fragment key={s}>
                <span style={{ color: '#00d4ff' }}>{s}</span>
                {i < 4 && <span style={{ color: '#334155' }}>→</span>}
              </React.Fragment>
            ))}
          </div>
          {expanded ? <ChevronUp size={16} color="#64748b" /> : <ChevronDown size={16} color="#64748b" />}
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '1rem 1.25rem' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '0.85rem',
          }}>

            {/* ══ Stage 1: OBSERVE ══ */}
            <div style={{
              background: 'rgba(0,212,255,0.04)', border: '1px solid rgba(0,212,255,0.2)',
              borderRadius: '12px', padding: '0.85rem',
            }}>
              <StageHeader icon={Eye} label="Observe Sensors" color="#00d4ff" step="1" />
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.1rem' }}>
                <ObserveRow label="Occupancy"      value={`${obs.occupancy}%`}            color="#f8fafc" />
                <ObserveRow label="Outdoor Temp"   value={`${obs.outdoorTemp.toFixed(1)}°C`} color="#00d4ff" />
                <ObserveRow label="Avg Zone Temp"  value={`${obs.avgZoneTemp.toFixed(1)}°C`} color={tempColor} />
                <ObserveRow label="Avg CO₂"        value={`${Math.round(obs.avgCo2)} ppm`}  color={co2Color} />
                <ObserveRow label="PMV Index"      value={`${obs.avgPmv >= 0 ? '+' : ''}${obs.avgPmv.toFixed(2)}`} color={pmvColor} />
                <ObserveRow label="Energy Demand"  value={`${obs.energyDemand.toFixed(1)} kW`} color="#d8b4fe" />
                <ObserveRow label="Carbon"         value={obs.carbonIntensity.toUpperCase()} color={
                  obs.carbonIntensity === 'high' ? '#ef4444' :
                  obs.carbonIntensity === 'moderate' ? '#f59e0b' : '#10b981'
                } />
              </div>
              {/* Status badges */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.6rem' }}>
                <Badge color={pmvColor}>
                  PMV {obs.pmvStatus === 'comfortable' ? '✓ OK' : '⚠ LIMIT'}
                </Badge>
                <Badge color={co2Color}>
                  CO₂ {obs.co2Status === 'good' ? '✓ GOOD' : obs.co2Status === 'elevated' ? '⚠ HIGH' : '🔴 CRITICAL'}
                </Badge>
              </div>
            </div>

            {/* ══ Stage 2: REASON ══ */}
            <div style={{
              background: 'rgba(124,58,237,0.04)', border: '1px solid rgba(124,58,237,0.2)',
              borderRadius: '12px', padding: '0.85rem',
            }}>
              <StageHeader icon={Brain} label="Reasoning Summary" color="#d8b4fe" step="2" />
              <p style={{
                margin: 0, fontSize: '0.78rem', color: '#e2e8f0',
                lineHeight: '1.55', fontStyle: 'italic',
                background: 'rgba(124,58,237,0.08)', padding: '0.6rem 0.75rem',
                borderRadius: '8px', borderLeft: '2px solid #7c3aed',
              }}>
                "{reasonText}"
              </p>
              {/* Strategy source */}
              {state.agent_stats?.strategy_source && (
                <div style={{ marginTop: '0.5rem', fontSize: '0.67rem', color: '#64748b' }}>
                  Strategy: {state.agent_stats.strategy_source}
                  {state.agent_stats.strategy_name && ` · ${state.agent_stats.strategy_name}`}
                </div>
              )}
            </div>

            {/* ══ Stage 3: ACT ══ */}
            <div style={{
              background: 'rgba(16,185,129,0.04)', border: '1px solid rgba(16,185,129,0.2)',
              borderRadius: '12px', padding: '0.85rem',
            }}>
              <StageHeader icon={Play} label="Control Actions" color="#10b981" step="3" />
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                <ActRow
                  label="HVAC Setpoint"
                  before={avg(prevHvac) || act.hvac?.before_avg}
                  applied={avg(currHvac) || act.hvac?.applied_avg}
                  unit="°C"
                  icon={Thermometer}
                  color="#10b981"
                />
                <ActRow
                  label="Lighting Level"
                  before={avg(prevLight) || act.lighting?.before_avg}
                  applied={avg(currLight) || act.lighting?.applied_avg}
                  unit="%"
                  icon={Lightbulb}
                  color="#f59e0b"
                />
                <ActRow
                  label="Ventilation"
                  before={avg(prevVent) || act.ventilation?.before_avg}
                  applied={avg(currVent) || act.ventilation?.applied_avg}
                  unit=" m³/s"
                  icon={Wind}
                  color="#00d4ff"
                />
              </div>
              {/* MCP tools used */}
              <div style={{ marginTop: '0.55rem', fontSize: '0.67rem', color: '#64748b', lineHeight: '1.4' }}>
                <span style={{ color: '#475569' }}>MCP:</span>{' '}
                {(act.mcp_tools_used || ['set_hvac_setpoint', 'set_lighting_level', 'set_ventilation_rate'])
                  .map(t => t.replace('set_', '').replace('_', ' ')).join(' · ')}
              </div>
            </div>

            {/* ══ Stage 4: VALIDATE ══ */}
            <div style={{
              background: hasClamping ? 'rgba(245,158,11,0.05)' : 'rgba(16,185,129,0.04)',
              border: `1px solid ${hasClamping ? 'rgba(245,158,11,0.3)' : 'rgba(16,185,129,0.2)'}`,
              borderRadius: '12px', padding: '0.85rem',
            }}>
              <StageHeader icon={ShieldCheck} label="Safety Validator" color={hasClamping ? '#f59e0b' : '#10b981'} step="4" />

              {/* Status line */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.6rem' }}>
                {hasClamping ? (
                  <>
                    <AlertTriangle size={16} color="#f59e0b" />
                    <span style={{ color: '#f59e0b', fontWeight: 'bold', fontSize: '0.8rem' }}>SAFETY OVERRIDE</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 size={16} color="#10b981" />
                    <span style={{ color: '#10b981', fontWeight: 'bold', fontSize: '0.8rem' }}>SAFE ACTION APPLIED</span>
                  </>
                )}
              </div>

              {/* Clamping events — only shown when clamping actually happened */}
              {hasClamping && safetyEvents.map((ev, i) => (
                <div key={i} style={{
                  background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.25)',
                  padding: '0.4rem 0.55rem', borderRadius: '6px', fontSize: '0.7rem',
                  color: '#fcd34d', marginBottom: '0.35rem',
                }}>
                  <div style={{ fontWeight: 'bold' }}>
                    {ev.type?.toUpperCase()} — Zone {ev.zone?.toUpperCase()}
                  </div>
                  <div>
                    LLM Proposed: <span style={{ color: '#ef4444' }}>{ev.proposed}{ev.type === 'hvac' ? '°C' : ev.type === 'lighting' ? '%' : ' m³/s'}</span>
                    {' → '}Applied: <span style={{ color: '#10b981', fontWeight: 'bold' }}>{ev.applied}{ev.type === 'hvac' ? '°C' : ev.type === 'lighting' ? '%' : ' m³/s'}</span>
                  </div>
                  <div style={{ color: '#94a3b8', fontSize: '0.65rem', marginTop: '2px' }}>
                    Limit: {ev.limit} · Value clamped to safe operating range
                  </div>
                </div>
              ))}

              {/* Constraints summary (always visible) */}
              <div style={{
                background: 'rgba(0,0,0,0.25)', padding: '0.4rem 0.55rem',
                borderRadius: '6px', fontSize: '0.67rem', color: '#64748b',
                lineHeight: '1.5',
              }}>
                <div>HVAC: {validate.bounds?.hvac || '18°C – 28°C'}</div>
                <div>PMV target: {validate.bounds?.pmv_target || '-0.5 to +0.5'}</div>
                <div>CO₂ max: {validate.bounds?.co2_max || '1000 ppm'}</div>
                <div>Vent min: {validate.bounds?.ventilation_min || '0.006 m³/s'}</div>
              </div>
            </div>

            {/* ══ Stage 5: LEARN ══ */}
            <div style={{
              background: 'rgba(59,130,246,0.04)', border: '1px solid rgba(59,130,246,0.2)',
              borderRadius: '12px', padding: '0.85rem',
              gridColumn: 'span 1',
            }}>
              <StageHeader icon={TrendingUp} label="Outcome Feedback" color="#60a5fa" step="5" />

              {learn.outcome === 'initializing' ? (
                <div style={{ color: '#64748b', fontSize: '0.78rem', fontStyle: 'italic' }}>
                  Establishing baseline observations for adaptive learning...
                </div>
              ) : (
                <>
                  <div style={{
                    background: 'rgba(0,0,0,0.25)', padding: '0.45rem 0.6rem',
                    borderRadius: '6px', marginBottom: '0.5rem',
                  }}>
                    <div style={{ fontSize: '0.67rem', color: '#64748b', marginBottom: '0.2rem' }}>PREVIOUS ACTION</div>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>{learn.prev_action_desc}</div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', marginBottom: '0.5rem' }}>
                    {learn.energy_delta_pct !== undefined && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem' }}>
                        <span style={{ color: '#64748b' }}>Energy change</span>
                        <span style={{
                          color: learn.energy_delta_pct > 0 ? '#10b981' : '#ef4444',
                          fontWeight: 'bold', fontFamily: 'monospace',
                        }}>
                          {learn.energy_delta_pct > 0 ? '▼' : '▲'} {Math.abs(learn.energy_delta_pct).toFixed(1)}%
                        </span>
                      </div>
                    )}
                    {learn.pmv_delta !== undefined && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem' }}>
                        <span style={{ color: '#64748b' }}>PMV delta</span>
                        <span style={{ color: '#d8b4fe', fontWeight: 'bold', fontFamily: 'monospace' }}>
                          {learn.pmv_delta >= 0 ? '+' : ''}{learn.pmv_delta.toFixed(3)}
                        </span>
                      </div>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem' }}>
                      <span style={{ color: '#64748b' }}>Comfort status</span>
                      <span style={{ color: learn.comfort_maintained ? '#10b981' : '#f59e0b', fontWeight: 'bold' }}>
                        {learn.comfort_maintained ? '✓ Maintained' : '⚠ Impacted'}
                      </span>
                    </div>
                  </div>

                  {/* Outcome pill */}
                  <div style={{
                    background: learn.outcome === 'successful'
                      ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                    border: `1px solid ${learn.outcome === 'successful' ? '#10b981' : '#f59e0b'}`,
                    borderRadius: '8px', padding: '0.35rem 0.6rem',
                    fontSize: '0.72rem',
                    color: learn.outcome === 'successful' ? '#34d399' : '#fcd34d',
                    fontWeight: 'bold',
                  }}>
                    {learn.outcome === 'successful' ? '✓' : '◈'} {learn.outcome_desc}
                  </div>
                </>
              )}
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
