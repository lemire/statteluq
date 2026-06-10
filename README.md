# Explorateur des inscriptions TELUQ

Application interactive d'exploration des données d'effectifs étudiants de la TELUQ (inscriptions par cours et par programme).

Inspirée de l'expérience **Our World in Data** : vous définissez des « ensembles » (groupes) de cours ou de programmes, puis vous les tracez sur des périodes et à différentes granularités temporelles. Les graphiques sont interactifs avec Plotly.

## Fonctionnalités principales

### Onglet Cours
- **Ensembles personnalisés** : 
  - Boutons rapides par préfixe (`INF*`, `ADM*`, `FIN*`, `EDU*`, …)
  - Recherche + multisélection manuelle
  - Bouton spécial **"Tous les cours"** (tous les ~2200 sigles, géré efficacement)
- **Groupes automatiques par département** : Sélectionnez un département (ST, ESA, SHLC, ED, …) → génération auto de groupes par préfixe de sigle (ex: `ST-INF`, `ST-ENV`, `ESA-ADM`…)
- **Explosion en cours individuels** : Choisissez un préfixe (ex: `INF`) pour tracer **chaque cours spécifique** (INF 1100, INF 1130, …) comme une ligne séparée sur le même graphique.
- **Cours individuels par département** : Filtrez par département(s) et sélectionnez des sigles précis à tracer individuellement.
- **Métriques** : Inscriptions TELUQ, Inscriptions totales (inclut BCI), Étudiants nouveaux/anciens, EETP TELUQ
- **Granularité** : 
  - Par trimestre
  - Par année civile
  - Par **année académique (début automne)**
- Filtre temporel précis + presets « 5 dernières années » / « Toute la période »
- **Graphiques Plotly** : lignes ou aires empilées, **empilage relatif (0-100 %)**, axe Y forcé à 0, survol unifié, zoom, export
- **Téléchargement** : SVG (haute qualité) + CSV des données du graphique
- Tableau des données + export CSV

### Onglet Programmes
- Même logique pour les programmes (296 programmes)
- Granularité identique
- Métrique unique : Total des inscriptions

## Lancer l'application

### Prérequis
- Python 3.10+ (recommandé 3.13 pour stabilité avec DuckDB)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (gestionnaire de projet Python moderne)

### Installation des dépendances (une seule fois)
```bash
cd /chemin/vers/statteluq
uv sync
```

`uv sync` crée automatiquement un environnement virtuel (`.venv`) et installe les dépendances déclarées dans `pyproject.toml`.

Vous pouvez aussi utiliser `uv run ...` directement (il synchronise à la volée).

### Lancement manuel
```bash
uv run streamlit run app.py
```

L'application s'ouvre dans votre navigateur à l'adresse : **http://localhost:8501**

### Scripts de contrôle (recommandé)

Trois scripts sont fournis pour démarrer/arrêter l'application en arrière-plan :

```bash
./start.sh      # Démarre l'app (port 8501 par défaut). Écrit le PID dans .streamlit.pid
./stop.sh       # Arrête l'app proprement
./restart.sh    # Redémarre l'app
```

- Le port peut être changé via la variable d'environnement : `PORT=8502 ./start.sh`
- Les logs sont écrits dans `.streamlit.log`
- Les scripts utilisent `uv run` et gèrent automatiquement l'environnement.

Si vous n'avez pas Python 3.13, installez-le :
```bash
brew install python@3.13
```

> **Note** : `requirements.txt` est conservé pour compatibilité, mais `pyproject.toml` (et `uv.lock`) est la source de vérité pour les dépendances.

## Structure des données

- `Statistiques par cours avec MATCI.csv` : ~485 000 lignes, trimestres 2002→2026, >2200 sigles
- `Nbre inscriptions par programmes.csv` : ~11 000 lignes, 1974→2026, 296 programmes

Les fichiers sont lus **directement** par DuckDB. Les données cours sont dédupliquées par date d'extraction la plus récente pour chaque (trimestre, sigle) afin d'éviter les sur-comptages.

## Exemples d'utilisation

### Exemple 1 : Groupes automatiques + explosion
1. Onglet Cours → section "Groupes automatiques par département et préfixe de sigle"
2. Sélectionnez le département `ST`
3. Dans "Groupes automatiques à tracer", cochez `ST-INF`
4. Dans "Préfixes à exploser", cochez `INF`
5. Choisissez "Par année académique (début automne)"
6. Observez la ligne totale `ST-INF` + les lignes individuelles de chaque cours INF du département ST

### Exemple 2 : Comparaison multi-départements
- Sélectionnez `ST` et `ESA`
- Cochez `ST-INF` et `ESA-INF`
- Passez en empilage relatif (0-100 %) pour voir la part de chaque groupe dans le temps

### Exemple 3 : Tous les cours
- Créez l'ensemble spécial **"Tous les cours"** (bouton dédié)
- Sélectionnez-le dans "Groupes à afficher"
- Utilisez la granularité "Par année civile" pour voir l'évolution globale des inscriptions

## Personnalisation / export des ensembles
Dans chaque onglet, un accordéon « Exporter / Importer les ensembles (JSON) » permet de sauvegarder vos définitions de groupes et de les recharger plus tard.

## Dépannage
- Données non visibles : vérifiez que les deux CSV sont dans le même dossier que `app.py`
- Export SVG : installez `kaleido` si nécessaire (`uv pip install kaleido` ou `uv add kaleido`)
- Performance : DuckDB est très rapide même sur 485k lignes ; les agrégations sont quasi-instantanées

## Crédits
- **DuckDB** : backend analytique (requêtes directes sur CSV)
- **Plotly** : graphiques interactifs publication-ready
- **Streamlit** : interface web

Données : TELUQ — direction des registres / analyse institutionnelle.
