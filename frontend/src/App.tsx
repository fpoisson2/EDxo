import './App.css'

function App() {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'

  return (
    <div className="app">
      <header className="app__header">
        <p className="app__eyebrow">EDxo</p>
        <h1 className="app__title">Nouvelle interface React</h1>
        <p className="app__subtitle">
          Shell Vite prêt à consommer l’API Flask. Ajoutez vos routes, vues et
          composants UI pour remplacer progressivement les templates Jinja.
        </p>
      </header>

      <main className="app__content">
        <section className="app__section">
          <h2>Étapes suivantes</h2>
          <ol>
            <li>Mappez les écrans existants et les endpoints nécessaires.</li>
            <li>Exposez les routes JSON côté Flask pour les données manquantes.</li>
            <li>
              Implémentez les premières pages React en consommant l’API via des
              hooks ou un client de données.
            </li>
          </ol>
        </section>

        <section className="app__section">
          <h2>Configuration actuelle</h2>
          <p>
            API Flask par défaut: <code>{apiBaseUrl}</code>
          </p>
          <p>
            Changez la valeur via <code>VITE_API_BASE_URL</code> ou{' '}
            <code>VITE_API_PROXY_TARGET</code> dans vos fichiers <code>.env</code>.
          </p>
        </section>
      </main>
    </div>
  )
}

export default App
