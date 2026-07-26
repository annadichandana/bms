import { useState, useEffect, useRef } from 'react';

export function useWebSocket(url) {
  const [state, setState] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const ws = useRef(null);
  const reconnectTimeout = useRef(null);
  const retryCount = useRef(0);

  useEffect(() => {
    function connect() {
      console.log('Connecting to WS:', url);
      ws.current = new WebSocket(url);

      ws.current.onopen = () => {
        console.log('WS Connected');
        setIsConnected(true);
        retryCount.current = 0;
      };

      ws.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setState(data);
          setLastUpdate(new Date());
        } catch (err) {
          console.error('Failed to parse WS message:', err);
        }
      };

      ws.current.onclose = () => {
        setIsConnected(false);
        console.log('WS Disconnected');
        
        // Exponential backoff
        const timeout = Math.min(1000 * (2 ** retryCount.current), 30000);
        console.log(`Reconnecting in ${timeout}ms...`);
        reconnectTimeout.current = setTimeout(connect, timeout);
        retryCount.current += 1;
      };

      ws.current.onerror = (err) => {
        console.error('WS Error:', err);
        ws.current.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimeout.current);
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [url]);

  return { state, isConnected, lastUpdate };
}
