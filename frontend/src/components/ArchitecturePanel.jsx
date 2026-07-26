import React from 'react';
import { ShieldAlert, Layers, Cloud, Server, Cpu, Activity, ArrowRight, ShieldCheck, CheckCircle2 } from 'lucide-react';

export function ArchitecturePanel() {
  return (
    <div className="glass animate-fade-in-up" style={{
      padding: '1.25rem',
      borderRadius: '16px',
      border: '1.5px solid rgba(124, 58, 237, 0.4)',
      marginBottom: '1rem',
      background: 'rgba(15, 23, 42, 0.85)',
      boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.4)'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <Layers className="text-[#7c3aed]" size={22} />
          <h3 style={{ margin: 0, fontSize: '1.15rem', color: '#f8fafc', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            ARIA CLOSED-LOOP MCP & SAFETY ARCHITECTURE
          </h3>
        </div>
        <div style={{ fontSize: '0.75rem', color: '#d8b4fe', background: 'rgba(124, 58, 237, 0.2)', padding: '0.3rem 0.75rem', borderRadius: '12px', border: '1px solid #7c3aed' }}>
          RESILIENCE & SAFETY GUARDRAILS ACTIVE
        </div>
      </div>

      {/* Positioning Statement */}
      <blockquote style={{
        margin: '0 0 1rem 0',
        padding: '0.75rem 1rem',
        background: 'rgba(124, 58, 237, 0.12)',
        borderLeft: '4px solid #7c3aed',
        borderRadius: '8px',
        color: '#d8b4fe',
        fontSize: '0.84rem',
        fontWeight: '500',
        lineHeight: '1.45'
      }}>
        "ARIA is a resilient closed-loop autonomous BMS that combines LLM-based decision-making, MCP tool execution, safety validation, and EnergyPlus simulation feedback."
      </blockquote>

      {/* Requirement #4: Visual MCP Flow Diagram */}
      <div style={{
        background: 'rgba(0, 0, 0, 0.4)', padding: '0.85rem 1rem', borderRadius: '12px',
        border: '1px solid rgba(255, 255, 255, 0.1)', marginBottom: '1rem'
      }}>
        <div style={{ fontSize: '0.75rem', color: '#00d4ff', fontWeight: 'bold', textTransform: 'uppercase', marginBottom: '0.5rem' }}>
          CLOSED-LOOP MCP DATAFLOW PIPELINE:
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexWrap: 'wrap', gap: '0.5rem', fontSize: '0.74rem', color: '#f8fafc'
        }}>
          <div style={{ background: 'rgba(59, 130, 246, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #3b82f6' }}>EnergyPlus</div>
          <ArrowRight size={14} className="text-[#94a3b8]" />
          <div style={{ background: 'rgba(0, 212, 255, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #00d4ff' }}>Building State</div>
          <ArrowRight size={14} className="text-[#94a3b8]" />
          <div style={{ background: 'rgba(124, 58, 237, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #7c3aed' }}>ARIA Agent</div>
          <ArrowRight size={14} className="text-[#94a3b8]" />
          <div style={{ background: 'rgba(16, 185, 129, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #10b981' }}>Groq LLaMA</div>
          <ArrowRight size={14} className="text-[#94a3b8]" />
          <div style={{ background: 'rgba(245, 158, 11, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #f59e0b' }}>MCP Tool Calls</div>
          <ArrowRight size={14} className="text-[#94a3b8]" />
          <div style={{ background: 'rgba(239, 68, 68, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #ef4444' }}>Safety Validation</div>
          <ArrowRight size={14} className="text-[#94a3b8]" />
          <div style={{ background: 'rgba(16, 185, 129, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #10b981' }}>Controls</div>
          <ArrowRight size={14} className="text-[#94a3b8]" />
          <div style={{ background: 'rgba(59, 130, 246, 0.2)', padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid #3b82f6' }}>Feedback</div>
        </div>

        {/* Human-Readable MCP Tools: Req #4 */}
        <div style={{ marginTop: '0.6rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
          <strong>Registered MCP Tools:</strong> get_all_zones_status(), get_energy_metrics(), get_weather_forecast(), get_occupancy_schedule(), set_hvac_setpoint(), set_lighting_level(), set_ventilation_rate()
        </div>
      </div>

      {/* Requirement #5: Safety Validation Guardrail Diagram */}
      <div style={{
        background: 'rgba(245, 158, 11, 0.08)', padding: '0.85rem 1rem', borderRadius: '12px',
        border: '1px solid rgba(245, 158, 11, 0.3)', marginBottom: '1rem'
      }}>
        <div style={{ fontSize: '0.75rem', color: '#f59e0b', fontWeight: 'bold', textTransform: 'uppercase', marginBottom: '0.4rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <ShieldAlert size={16} /> SAFETY VALIDATION GUARDRAIL PIPELINE:
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', fontSize: '0.74rem', color: '#f8fafc' }}>
          <span style={{ color: '#d8b4fe' }}>LLM PROPOSES ACTION</span> →
          <span style={{ color: '#f59e0b', fontWeight: 'bold' }}>SAFETY VALIDATOR</span> →
          <span style={{ color: '#34d399' }}>CLAMP / VALIDATE VALUES</span> →
          <span style={{ color: '#10b981', fontWeight: 'bold' }}>SAFE ACTION APPLIED</span>
        </div>
        <div style={{ fontSize: '0.7rem', color: '#fcd34d', marginTop: '0.4rem', background: 'rgba(0,0,0,0.3)', padding: '0.4rem 0.6rem', borderRadius: '6px' }}>
          <strong>Example Safety Clamping:</strong> LLM proposed HVAC = 18°C → Safety Validator clamped to <strong>20°C</strong> (ASHRAE 55 operating limit enforcement).
        </div>
      </div>

      {/* Requirement #6: 3-Layer Fallback Resilience Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '0.75rem' }}>
        
        {/* Layer 1: Groq Cloud LLM */}
        <div style={{
          background: 'rgba(0, 0, 0, 0.35)', padding: '0.85rem', borderRadius: '10px',
          borderTop: '3px solid #10b981', display: 'flex', flexDirection: 'column', gap: '0.35rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: '#10b981', fontSize: '0.78rem', fontWeight: 'bold' }}>🟢 GROQ + MCP ACTIVE</span>
            <Cloud size={15} className="text-[#10b981]" />
          </div>
          <div style={{ fontSize: '0.75rem', color: '#f8fafc', fontWeight: '600' }}>
            Groq LLaMA 3.1 8B Instant
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            Primary reasoning & native MCP tool calling (30,000 TPM limit)
          </div>
        </div>

        {/* Layer 2: Local LLM Fallback */}
        <div style={{
          background: 'rgba(0, 0, 0, 0.35)', padding: '0.85rem', borderRadius: '10px',
          borderTop: '3px solid #f59e0b', display: 'flex', flexDirection: 'column', gap: '0.35rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: '#f59e0b', fontSize: '0.78rem', fontWeight: 'bold' }}>🟡 OLLAMA LOCAL ACTIVE</span>
            <Server size={15} className="text-[#f59e0b]" />
          </div>
          <div style={{ fontSize: '0.75rem', color: '#f8fafc', fontWeight: '600' }}>
            Ollama Phi-3 / LLaMA 3.2
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            Zero-internet structured JSON fallback when cloud offline
          </div>
        </div>

        {/* Layer 3: Rule-Based Fallback */}
        <div style={{
          background: 'rgba(0, 0, 0, 0.35)', padding: '0.85rem', borderRadius: '10px',
          borderTop: '3px solid #3b82f6', display: 'flex', flexDirection: 'column', gap: '0.35rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: '#60a5fa', fontSize: '0.78rem', fontWeight: 'bold' }}>🔵 RULE-BASED FALLBACK</span>
            <Cpu size={15} className="text-[#3b82f6]" />
          </div>
          <div style={{ fontSize: '0.75rem', color: '#f8fafc', fontWeight: '600' }}>
            ASHRAE 55 & 62.1 Optimizer
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            Deterministic rule-based fallback guarantees 100% uptime
          </div>
        </div>

      </div>
    </div>
  );
}

