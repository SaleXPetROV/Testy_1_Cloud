import React from 'react';

// Global error boundary. Turns a silent white screen (e.g. an unexpected
// runtime crash inside the Telegram iOS WKWebView) into a visible, actionable
// message with a Reload button — and surfaces the actual error text so the
// failure is diagnosable on the device instead of an empty page.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: (error && (error.message || String(error))) || 'Unknown error' };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    try { console.error('[ErrorBoundary]', error, info); } catch (e) { /* ignore */ }
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div
        data-testid="app-error-boundary"
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '16px',
          padding: '24px',
          textAlign: 'center',
          background: '#05060A',
          color: '#e6e6f0',
          fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
        }}
      >
        <div style={{ fontSize: '48px' }}>⚠️</div>
        <div style={{ fontSize: '18px', fontWeight: 700 }}>GRAM CITY</div>
        <div style={{ fontSize: '14px', opacity: 0.75, maxWidth: '340px' }}>
          Something went wrong while loading the app. Please reload.
        </div>
        <pre
          style={{
            fontSize: '11px',
            opacity: 0.5,
            maxWidth: '340px',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {this.state.message}
        </pre>
        <button
          type="button"
          onClick={() => {
            // Full hard reload of the SITE (not just an in-app/router reset):
            // navigate to the origin root so the whole app re-bootstraps from
            // scratch, clearing any corrupted in-memory/DOM state.
            try {
              window.location.replace(window.location.origin + '/');
            } catch (e) {
              try { window.location.reload(); } catch (_) { /* ignore */ }
            }
          }}
          style={{
            marginTop: '8px',
            padding: '12px 28px',
            borderRadius: '12px',
            border: 'none',
            background: '#00F0FF',
            color: '#000',
            fontWeight: 800,
            fontSize: '14px',
            cursor: 'pointer',
          }}
        >
          Reload
        </button>
      </div>
    );
  }
}
