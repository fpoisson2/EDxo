# EDxo Frontend (React + Vite)

Client React isolé destiné à remplacer progressivement les templates Flask/Jinja. Le projet utilise Vite + TypeScript pour bénéficier d’un rechargement rapide et d’une configuration légère.

## Installation

```bash
cd frontend
npm install
```

## Configuration

1. Copiez `.env.example` vers `.env.development` (ou `.env.local`).
2. Ajustez `VITE_API_BASE_URL` si le backend Flask n’est pas accessible sur `http://localhost:5000`.
3. Si vous souhaitez que Vite proxy automatiquement les appels `/api`, `/auth` ou `/tasks`, modifiez `VITE_API_PROXY_TARGET`.

## Démarrage

```bash
npm run dev
```

- Le serveur Vite démarre par défaut sur `http://localhost:5173`.
- Un proxy est configuré pour rediriger `/api`, `/auth` et `/tasks` vers le backend Flask.
- Les assets sont servis depuis `index.html`; intégrez le build dans votre reverse proxy ou servez-le via Flask si nécessaire.

## Vérification

- `npm run lint` pour vérifier les règles ESLint.
- `npm run build` pour générer le bundle de production (`dist/`).
- `npm run preview` pour tester localement la version compilée.

## Structure

```
frontend/
├── public/            # Assets statiques copiés tels quels
├── src/
│   ├── App.tsx        # Point d’entrée de l’UI React
│   ├── index.tsx      # Bootstrapping ReactDOM
│   └── index.css      # Style global minimal
└── vite.config.ts     # Configuration Vite + proxy backend
```

Ajoutez vos composants sous `src/` (ex. `src/features`, `src/components`) et pensez à brancher vos hooks de données sur l’API EDxo.
