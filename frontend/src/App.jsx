import { useState, useEffect } from 'react'
import { GoogleLogin } from '@react-oauth/google'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const PREFERENCES = [
  { id: 'food', emoji: '🍜', label: 'Food' },
  { id: 'nightlife', emoji: '🎉', label: 'Nightlife' },
  { id: 'beach', emoji: '🏖️', label: 'Beach' },
  { id: 'adventure', emoji: '🏔️', label: 'Adventure' },
  { id: 'luxury', emoji: '💎', label: 'Luxury' },
  { id: 'budget', emoji: '💰', label: 'Budget' },
  { id: 'shopping', emoji: '🛍️', label: 'Shopping' },
  { id: 'wellness', emoji: '🧘', label: 'Wellness' },
  { id: 'sightseeing', emoji: '🏛️', label: 'Culture' },
  { id: 'photography', emoji: '📸', label: 'Photography' },
]

const AGENT_NAMES = [
  { key: 'planner', emoji: '🧠', label: 'Planner' },
  { key: 'transport', emoji: '✈️', label: 'Transport' },
  { key: 'stay', emoji: '🏨', label: 'Stay' },
  { key: 'itinerary', emoji: '📍', label: 'Itinerary' },
  { key: 'budget', emoji: '💰', label: 'Budget' },
  { key: 'context', emoji: '🌦️', label: 'Context' },
  { key: 'negotiation', emoji: '⚔️', label: 'Negotiation' },
]

export default function App() {
  // Auth state
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(localStorage.getItem('token'))
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [authLoading, setAuthLoading] = useState(true)
  const [history, setHistory] = useState([])

  // App state
  const [form, setForm] = useState({
    destination: '',
    budget: '',
    duration: '',
    origin: 'Delhi',
    preferences: [],
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [elapsedMs, setElapsedMs] = useState(null)
  const [logs, setLogs] = useState([])
  const [expandedDays, setExpandedDays] = useState({})

  // Fetch current user on mount if token exists
  useEffect(() => {
    if (token) {
      fetch(`${API_BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      .then(res => {
        if (!res.ok) throw new Error("Invalid session")
        return res.json()
      })
      .then(data => {
        setUser(data)
        fetchHistory(token)
      })
      .catch(() => {
        setToken(null)
        localStorage.removeItem('token')
      })
      .finally(() => setAuthLoading(false))
    } else {
      setAuthLoading(false)
    }
  }, [token])

  const fetchHistory = async (t) => {
    try {
      const res = await fetch(`${API_BASE}/api/trips`, {
        headers: { Authorization: `Bearer ${t}` }
      })
      if (res.ok) {
        setHistory(await res.json())
      }
    } catch(e) { console.error(e) }
  }

  const handleGoogleSuccess = async (credentialResponse) => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: credentialResponse.credential })
      })
      if (!res.ok) throw new Error("Google login failed on backend")
      const data = await res.json()
      localStorage.setItem('token', data.token)
      setToken(data.token)
      setUser(data.user)
      fetchHistory(data.token)
    } catch (err) {
      alert("Login Failed: " + err.message)
    }
  }

  const handleGuestLogin = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/guest`, { method: 'POST' })
      const data = await res.json()
      localStorage.setItem('token', data.token)
      setToken(data.token)
      setUser(data.user)
      fetchHistory(data.token)
    } catch(err) {
      alert("Guest Login Failed")
    }
  }

  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
    setHistory([])
    setResult(null)
    setLogs([])
  }

  const togglePreference = (pref) => {
    setForm(f => ({
      ...f,
      preferences: f.preferences.includes(pref)
        ? f.preferences.filter(p => p !== pref)
        : [...f.preferences, pref]
    }))
  }

  const loadPastTrip = async (tripId) => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API_BASE}/api/trips/${tripId}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (!res.ok) throw new Error("Failed to load trip")
      const data = await res.json()
      
      // Load form details from past trip
      setForm({
        destination: data.request.destination || '',
        budget: data.request.budget || '',
        duration: data.request.duration || '',
        origin: data.request.origin || 'Delhi',
        preferences: data.request.preferences || [],
      })
      
      setResult(data.result)
      setLogs([]) 
      setExpandedDays({ 1: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.destination || !form.budget || !form.duration) return

    setLoading(true)
    setError(null)
    setResult(null)
    setLogs([])

    try {
      const res = await fetch(`${API_BASE}/api/trips`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          destination: form.destination,
          budget: parseFloat(form.budget),
          duration: parseInt(form.duration),
          preferences: form.preferences,
          origin: form.origin,
        })
      })

      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Planning failed')
      }

      const data = await res.json()
      setResult(data.result)
      setElapsedMs(data.elapsed_ms)
      setLogs(data.logs || [])
      setExpandedDays({ 1: true })
      
      // Refresh history sidebar
      fetchHistory(token)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const toggleDay = (day) => {
    setExpandedDays(prev => ({ ...prev, [day]: !prev[day] }))
  }

  // Loading Splash Screen
  if (authLoading) {
    return <div className="app loading-splash">Loading Agent Workspace...</div>
  }

  // Login Screen
  if (!user) {
    return (
      <div className="app login-container">
        <div className="glass-card login-card animate-slide-up">
          <div className="login-logo">🌍</div>
          <h1>Travel Planner AI</h1>
          <p>Multi-Agent reasoning for perfect itineraries</p>
          
          <div className="login-actions">
            <GoogleLogin
              onSuccess={handleGoogleSuccess}
              onError={() => alert('Google login failed')}
              useOneTap
              theme="filled_black"
              shape="pill"
            />
            <div className="login-divider"><span>OR</span></div>
            <button className="guest-btn" onClick={handleGuestLogin}>
              👤 Continue as Guest
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="app app-layout">
      {/* Sidebar for History */}
      <div className={`sidebar-overlay ${isSidebarOpen ? 'show' : ''}`} onClick={() => setIsSidebarOpen(false)}></div>
      <aside className={`sidebar glass-card ${isSidebarOpen ? 'open' : ''}`}>
        <div className="mobile-close-btn" onClick={() => setIsSidebarOpen(false)}>✕</div>
        
        <div className="sidebar-history">
          <h3 className="history-title">🗓️ Past Trips</h3>
          {history.length === 0 ? (
            <p className="no-history">No trips planned yet.</p>
          ) : (
            <div className="history-list">
              {history.map(t => (
                <div key={t.id} className="history-item" onClick={() => {
                   loadPastTrip(t.id);
                   setIsSidebarOpen(false);
                }}>
                  <div className="history-item-header">
                    <strong>{t.destination}</strong>
                    <span className="history-badge">{t.status}</span>
                  </div>
                  <div className="history-item-meta">
                    ₹{t.budget} • {t.duration} days
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="sidebar-footer">
          <div className="user-profile">
            {user.avatar_url ? (
              <img src={user.avatar_url} alt="avatar" className="avatar" referrerPolicy="no-referrer" />
            ) : (
              <div className="avatar-placeholder">👤</div>
            )}
            <div className="user-info">
              <span className="user-name">{user.name}</span>
              <span className="user-email">{user.is_guest ? 'Guest Session' : user.email}</span>
            </div>
          </div>
          <button className="logout-btn" onClick={logout}>Exit</button>
        </div>
      </aside>

      {/* Main App Content */}
      <div className="main-wrapper">
        <header className="header">
          <div className="mobile-menu-btn" onClick={() => setIsSidebarOpen(true)}>☰</div>
          <div className="header-content">
            <div className="logo">
              <span className="logo-icon">🌍</span>
              <div>
                <h1>Travel Planner AI</h1>
                <span className="logo-subtitle">A2A Multi-Agent System</span>
              </div>
            </div>
            <div className="header-badges">
              <div className="badge"><span className="badge-dot"></span> 7 Agents Online</div>
              <div className="badge">⚡ Cohere Powered</div>
            </div>
          </div>
        </header>

        <main className="main-content">
          <div className="content-grid">
            {/* Form Panel */}
            <div className="form-panel">
              <form className="glass-card" onSubmit={handleSubmit}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                 <h2 className="card-title">✨ Plan Your Trip</h2>
                 <button type="button" className="reset-btn" onClick={() => setResult(null)}>Reset</button>
                </div>
                <p className="card-subtitle">Let our AI agents create the perfect itinerary</p>

                <div className="form-group">
                  <label className="form-label">Destination</label>
                  <input
                    className="form-input"
                    type="text"
                    placeholder="e.g. Dubai, Tokyo, Goa, Paris"
                    value={form.destination}
                    onChange={e => setForm(f => ({ ...f, destination: e.target.value }))}
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Origin</label>
                  <input
                    className="form-input"
                    type="text"
                    placeholder="e.g. Delhi, Mumbai"
                    value={form.origin}
                    onChange={e => setForm(f => ({ ...f, origin: e.target.value }))}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Budget (₹)</label>
                  <input
                    className="form-input"
                    type="number"
                    placeholder="e.g. 20000"
                    min="1000"
                    value={form.budget}
                    onChange={e => setForm(f => ({ ...f, budget: e.target.value }))}
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Duration (Days)</label>
                  <input
                    className="form-input"
                    type="number"
                    placeholder="e.g. 5"
                    min="1"
                    max="30"
                    value={form.duration}
                    onChange={e => setForm(f => ({ ...f, duration: e.target.value }))}
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Preferences</label>
                  <div className="preferences-grid">
                    {PREFERENCES.map(pref => (
                      <label
                        key={pref.id}
                        className={`pref-chip ${form.preferences.includes(pref.id) ? 'active' : ''}`}
                      >
                        <input 
                          type="checkbox" 
                          checked={form.preferences.includes(pref.id)}
                          onChange={() => togglePreference(pref.id)} 
                        />
                        <span className="pref-emoji">{pref.emoji}</span>
                        {pref.label}
                      </label>
                    ))}
                  </div>
                </div>

                <button type="submit" className="submit-btn" disabled={loading}>
                  {loading ? (
                    <><span className="spinner"></span> Agents Working...</>
                  ) : (
                    <>🚀 Plan My Trip</>
                  )}
                </button>
              </form>
            </div>

            {/* Results Panel */}
            <div className="results-panel">
              {/* Loading State */}
              {loading && (
                <div className="glass-card loading-state animate-fade-in">
                  <div style={{ fontSize: '48px', marginBottom: '16px' }}>🤖</div>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '8px' }}>
                    Agents Collaborating...
                  </h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginBottom: '20px' }}>
                    7 AI agents are working together via A2A messaging
                  </p>
                  <div className="loading-agents">
                    {AGENT_NAMES.map((a, i) => (
                      <div key={a.key} className="agent-chip active">
                        {a.emoji} {a.label}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Error */}
              {error && (
                <div className="glass-card animate-fade-in" style={{ borderColor: 'var(--error)', background: 'var(--error-glow)' }}>
                  <h3 style={{ color: 'var(--error)', marginBottom: '8px' }}>❌ Error</h3>
                  <p style={{ color: 'var(--text-secondary)' }}>{error}</p>
                </div>
              )}

              {/* Empty State */}
              {!loading && !result && !error && (
                <div className="empty-state">
                  <div className="empty-icon">🗺️</div>
                  <h3>Ready to Explore?</h3>
                  <p>Fill in your trip details and let our AI agents<br/>craft the perfect travel plan for you.</p>
                </div>
              )}

              {/* Results */}
              {result && (
                <>
                  {/* Trip Summary */}
                  <div className="trip-summary animate-fade-in">
                    <h2>🎉 Your Trip to {result.destination || form.destination}</h2>
                    <div className="trip-meta">
                      <span className="meta-tag">📅 {result.duration || form.duration} Days</span>
                      <span className="meta-tag">💰 ₹{result.cost_breakdown?.budget?.toLocaleString()}</span>
                      {elapsedMs && <span className="meta-tag">⚡ {elapsedMs}ms</span>}
                      {result.negotiation_applied && (
                        <span className="meta-tag" style={{ color: 'var(--warning)' }}>⚔️ Negotiated</span>
                      )}
                    </div>
                    {result.summary && (
                      <p className="trip-summary-text">{result.summary}</p>
                    )}
                  </div>

                  {/* Negotiation Banner */}
                  {result.negotiation_applied && result.negotiation_changes?.length > 0 && (
                    <div className="negotiation-banner animate-slide-up">
                      <h4>⚔️ Budget Negotiation Applied</h4>
                      {result.negotiation_changes.map((change, i) => (
                        <div key={i} className="negotiation-change">{change}</div>
                      ))}
                    </div>
                  )}

                  {/* Transport */}
                  {result.transport?.options?.length > 0 && (
                    <div className="glass-card animate-slide-up">
                      <div className="section-header">
                        <span className="section-icon">✈️</span>
                        <h3>Transport Options</h3>
                      </div>
                      <div className="options-grid">
                        {result.transport.options.slice(0, 6).map((opt, i) => {
                          const isSelected = result.transport.selected?.provider === opt.provider
                          return (
                            <div key={i} className={`option-card ${isSelected ? 'selected' : ''}`}>
                              <div className="option-header">
                                <div>
                                  <div className="option-name">{opt.provider}</div>
                                  <div className="option-rating">⭐ {opt.rating}</div>
                                </div>
                                <div style={{ textAlign: 'right' }}>
                                  <div className="option-price">₹{opt.price?.toLocaleString()}</div>
                                  {isSelected && <span className="selected-badge">✓ Selected</span>}
                                </div>
                              </div>
                              <div className="option-details">
                                <span className="option-tag">{opt.mode}</span>
                                <span className="option-tag">{opt.departure} → {opt.arrival}</span>
                                <span className="option-tag">{opt.duration_hours}h</span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Stay */}
                  {result.stay?.options?.length > 0 && (
                    <div className="glass-card animate-slide-up">
                      <div className="section-header">
                        <span className="section-icon">🏨</span>
                        <h3>Accommodation Options</h3>
                      </div>
                      <div className="options-grid">
                        {result.stay.options.slice(0, 6).map((opt, i) => {
                          const isSelected = result.stay.selected?.name === opt.name
                          return (
                            <div key={i} className={`option-card ${isSelected ? 'selected' : ''}`}>
                              <div className="option-header">
                                <div>
                                  <div className="option-name">{opt.name}</div>
                                  <div className="option-rating">⭐ {opt.rating}</div>
                                </div>
                                <div style={{ textAlign: 'right' }}>
                                  <div className="option-price">₹{opt.price_per_night?.toLocaleString()}/night</div>
                                  {isSelected && <span className="selected-badge">✓ Selected</span>}
                                </div>
                              </div>
                              <div className="option-details">
                                <span className="option-tag">{opt.type}</span>
                                <span className="option-tag">{opt.distance_to_center_km}km to center</span>
                                {opt.amenities?.slice(0, 3).map((a, j) => (
                                  <span key={j} className="option-tag">{a}</span>
                                ))}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Itinerary */}
                  {result.itinerary?.length > 0 && (
                    <div className="glass-card animate-slide-up">
                      <div className="section-header">
                        <span className="section-icon">📍</span>
                        <h3>Day-wise Itinerary</h3>
                      </div>
                      <div className="itinerary-timeline">
                        {result.itinerary.map(day => (
                          <div key={day.day} className="day-card">
                            <div className="day-header" onClick={() => toggleDay(day.day)}>
                              <span className="day-number">
                                📅 Day {day.day}
                                <span style={{ fontWeight: 400, fontSize: '13px', color: 'var(--text-muted)' }}>
                                  — {day.activities?.length || 0} activities, {day.meals?.length || 0} meals
                                </span>
                              </span>
                              <span className="day-cost">₹{day.day_cost?.toLocaleString()}</span>
                            </div>
                            {expandedDays[day.day] && (
                              <div className="day-activities">
                                {[...(day.activities || []), ...(day.meals || [])]
                                  .sort((a, b) => (a.time || '').localeCompare(b.time || ''))
                                  .map((act, i) => (
                                    <div key={i} className="activity-item">
                                      <span className="activity-time">{act.time}</span>
                                      <div className="activity-info">
                                        <div className="activity-name">
                                          {act.category === 'food' ? '🍽️' : '🎯'} {act.name}
                                        </div>
                                        <div className="activity-desc">{act.description}</div>
                                      </div>
                                      {act.cost > 0 && (
                                        <span className="activity-cost">₹{act.cost?.toLocaleString()}</span>
                                      )}
                                    </div>
                                  ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* LLM Suggestions */}
                      {result.llm_itinerary_suggestions && (
                        <div style={{ marginTop: '16px', padding: '14px', background: 'rgba(99,102,241,0.08)', borderRadius: '12px' }}>
                          <h4 style={{ fontSize: '14px', marginBottom: '8px', color: '#a5b4fc' }}>🤖 AI Suggestions</h4>
                          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.7', whiteSpace: 'pre-line' }}>
                            {result.llm_itinerary_suggestions}
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Cost Breakdown */}
                  {result.cost_breakdown && (
                    <div className="glass-card cost-card animate-slide-up">
                      <div className="section-header">
                        <span className="section-icon">💰</span>
                        <h3>Cost Breakdown</h3>
                      </div>
                      <div className="cost-rows">
                        <div className="cost-row">
                          <span className="cost-label">✈️ Transport</span>
                          <span className="cost-value">₹{result.cost_breakdown.transport?.toLocaleString()}</span>
                        </div>
                        <div className="cost-row">
                          <span className="cost-label">🏨 Accommodation</span>
                          <span className="cost-value">₹{result.cost_breakdown.accommodation?.toLocaleString()}</span>
                        </div>
                        <div className="cost-row">
                          <span className="cost-label">🎯 Activities</span>
                          <span className="cost-value">₹{result.cost_breakdown.activities?.toLocaleString()}</span>
                        </div>
                        <div className="cost-row">
                          <span className="cost-label">🍽️ Food</span>
                          <span className="cost-value">₹{result.cost_breakdown.food?.toLocaleString()}</span>
                        </div>
                        <div className="cost-row">
                          <span className="cost-label">🎒 Miscellaneous</span>
                          <span className="cost-value">₹{result.cost_breakdown.miscellaneous?.toLocaleString()}</span>
                        </div>
                        <div className="cost-row cost-total">
                          <span className="cost-label">Total</span>
                          <span className="cost-value">₹{result.cost_breakdown.total?.toLocaleString()}</span>
                        </div>
                      </div>
                      <div className={`budget-status ${result.cost_breakdown.within_budget ? 'under' : 'over'}`}>
                        {result.cost_breakdown.within_budget
                          ? `✅ Within budget — ₹${result.cost_breakdown.savings?.toLocaleString()} saved!`
                          : `⚠️ Over budget by ₹${Math.abs(result.cost_breakdown.savings || 0).toLocaleString()}`
                        }
                      </div>
                    </div>
                  )}

                  {/* Context / Weather */}
                  {result.context && (
                    <div className="glass-card animate-slide-up">
                      <div className="section-header">
                        <span className="section-icon">🌦️</span>
                        <h3>Travel Context</h3>
                      </div>
                      <div className="context-grid">
                        <div className="context-item">
                          <h5>🌡️ Temperature</h5>
                          <div className="context-value">
                            {result.context.weather?.temp_high}° / {result.context.weather?.temp_low}°
                          </div>
                        </div>
                        <div className="context-item">
                          <h5>☁️ Conditions</h5>
                          <div className="context-value" style={{ fontSize: '14px' }}>
                            {result.context.weather?.condition}
                          </div>
                        </div>
                        <div className="context-item">
                          <h5>👥 Crowd Level</h5>
                          <div className="context-value">{result.context.crowd_level}</div>
                        </div>
                        <div className="context-item">
                          <h5>🌧️ Rainfall</h5>
                          <div className="context-value">{result.context.weather?.rainfall_mm} mm</div>
                        </div>
                      </div>

                      {result.context.events?.length > 0 && (
                        <div style={{ marginTop: '16px' }}>
                          <h4 style={{ fontSize: '14px', marginBottom: '8px' }}>🎪 Events</h4>
                          {result.context.events.map((event, i) => (
                            <div key={i} style={{ padding: '8px 0', fontSize: '13px', color: 'var(--text-secondary)' }}>
                              <strong>{event.name}</strong> — {event.description}
                            </div>
                          ))}
                        </div>
                      )}

                      {result.context.tips?.length > 0 && (
                        <div style={{ marginTop: '16px' }}>
                          <h4 style={{ fontSize: '14px', marginBottom: '8px' }}>Travel Tips</h4>
                          <ul className="tips-list">
                            {result.context.tips.map((tip, i) => (
                              <li key={i}>{tip}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Agent Logs */}
                  {logs.length > 0 && (
                    <div className="glass-card logs-card animate-slide-up">
                      <div className="section-header">
                        <span className="section-icon">📊</span>
                        <h3>Agent Decision Trace ({logs.length})</h3>
                      </div>
                      <div className="log-entries">
                        {logs.map((log, i) => {
                          let className = 'log-entry'
                          if (log.includes('DECISION')) className += ' decision'
                          else if (log.includes('WARNING')) className += ' warning'
                          else if (log.includes('ERROR')) className += ' error'
                          return <div key={i} className={className}>{log}</div>
                        })}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
