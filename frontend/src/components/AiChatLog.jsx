import React, { useEffect, useRef } from 'react';
import { Brain, ArrowRight } from 'lucide-react';

export function AiChatLog({ aiLog = [] }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [aiLog]);

  return (
    <div className="glass" style={{ 
      display: 'flex', flexDirection: 'column', height: '100%', 
      borderLeft: '4px solid #7c3aed'
    }}>
      <div style={{ 
        padding: '1rem', borderBottom: '1px solid rgba(255,255,255,0.1)',
        display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(124, 58, 237, 0.1)'
      }}>
        <Brain className="text-[#7c3aed] animate-pulse" size={20} />
        <h3 style={{ margin: 0, textTransform: 'uppercase', letterSpacing: '0.05em' }}>ARIA Intelligence Log</h3>
      </div>

      <div ref={scrollRef} style={{ 
        flex: 1, overflowY: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem'
      }}>
        {aiLog.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', textAlign: 'center', marginTop: '2rem' }}>
            ARIA is initializing... monitoring environment...
          </div>
        ) : (
          aiLog.map((log, i) => {
            const isLatest = i === aiLog.length - 1;
            const timeStr = new Date(log.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
            
            return (
              <div key={i} className={`animate-slide-in-right`} style={{ 
                background: 'rgba(0,0,0,0.3)', padding: '0.75rem', borderRadius: '8px',
                borderLeft: '2px solid rgba(255,255,255,0.1)'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  <span>{timeStr}</span>
                  {log.energy_impact && (
                    <span style={{ color: log.energy_impact < 0 ? '#10b981' : '#ef4444', fontWeight: 'bold' }}>
                      {log.energy_impact > 0 ? '+' : ''}{log.energy_impact} kW
                    </span>
                  )}
                </div>
                
                <p style={{ margin: '0 0 0.75rem 0', fontSize: '0.875rem', fontStyle: 'italic', lineHeight: '1.4' }}>
                  "{log.reasoning}"
                </p>
                
                {log.actions && log.actions.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    {log.actions.map((act, j) => (
                      <div key={j} style={{ 
                        display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.75rem',
                        background: 'rgba(124, 58, 237, 0.2)', padding: '0.25rem 0.5rem', borderRadius: '4px',
                        color: '#d8b4fe', width: 'fit-content'
                      }}>
                        <ArrowRight size={12} /> {act}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
