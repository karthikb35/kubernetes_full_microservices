import { useEffect, useState } from 'react'
import './App.css'

const NAV = ['events', 'orders']

function useFetch(url) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(url)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [url])

  return { data, loading, error }
}

function EventsTab() {
  const { data, loading, error } = useFetch('/api/catalog/events')
  return (
    <section>
      <h2>Upcoming Events</h2>
      {loading && <p className="muted">Loading events…</p>}
      {error && <p className="error">Could not reach catalog service: {error}</p>}
      {data && (
        Array.isArray(data)
          ? <ul className="card-list">
              {data.map((e, i) => (
                <li key={i} className="card">
                  <strong>{e.name ?? e.title ?? JSON.stringify(e)}</strong>
                  {e.date && <span className="badge">{e.date}</span>}
                </li>
              ))}
            </ul>
          : <pre>{JSON.stringify(data, null, 2)}</pre>
      )}
    </section>
  )
}

function OrdersTab() {
  const { data, loading, error } = useFetch('/api/orders')
  return (
    <section>
      <h2>My Orders</h2>
      {loading && <p className="muted">Loading orders…</p>}
      {error && <p className="error">Could not reach orders service: {error}</p>}
      {data && <pre>{JSON.stringify(data, null, 2)}</pre>}
    </section>
  )
}

export default function App() {
  const [tab, setTab] = useState('events')

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo">🎟</span>
          <div>
            <h1>TicketHub</h1>
            <p>Event ticketing platform</p>
          </div>
        </div>
        <nav>
          {NAV.map(t => (
            <button
              key={t}
              className={tab === t ? 'active' : ''}
              onClick={() => setTab(t)}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      <main>
        {tab === 'events' && <EventsTab />}
        {tab === 'orders' && <OrdersTab />}
      </main>

      <footer>TicketHub — Kubernetes Architecture Demo</footer>
    </div>
  )
}
