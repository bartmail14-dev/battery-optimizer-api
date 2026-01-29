# 🔋 Battery Optimizer API

**Backend API voor batterij-optimalisatie en energieprofiel analyse**

## 📍 Live URLs

- **API:** https://comcalculator-production.up.railway.app
- **Documentatie:** https://comcalculator-production.up.railway.app/docs
- **Health Check:** https://comcalculator-production.up.railway.app/health

## 🎯 Wat doet deze API?

Deze API helpt bij het bepalen van de optimale batterijgrootte voor zakelijke klanten. Je uploadt een CSV met kwartierwaarden en krijgt terug:

1. **Profielanalyse** - Piekverbruik, baseload, totaal verbruik
2. **Batterij-optimalisatie** - Optimale grootte, ROI, terugverdientijd
3. **Data verrijking** - Netbeheerder, tarieven, subsidies, congestie

## 🚀 Belangrijkste Endpoints

| Endpoint | Beschrijving |
|----------|--------------|
| `POST /api/v1/upload` | Upload CSV met kwartierwaarden |
| `POST /api/v1/analyze` | Analyseer energieprofiel |
| `POST /api/v1/optimize` | Bereken optimale batterij |
| `POST /api/v1/enrich` | Verrijk met marktdata |
| `GET /api/v1/enrich/tarieven/{postcode}` | Haal netbeheer tarieven op |

## 📁 Project Structuur

```
app/
├── main.py                 # FastAPI applicatie (START HIER)
├── config.py               # Configuratie (environment variables)
├── api/routes/             # API endpoints
│   ├── upload.py           # CSV upload
│   ├── analyze.py          # Profiel analyse
│   ├── optimize.py         # Batterij optimalisatie
│   ├── export.py           # Export naar CSV/Excel
│   └── enrich.py           # Data verrijking
├── services/               # Business logic
│   ├── enrichment.py       # Hoofdservice verrijking
│   ├── clients/            # Externe API clients
│   │   ├── entsoe.py       # ENTSO-E stroomprijzen
│   │   ├── tennet.py       # TenneT onbalansprijzen
│   │   ├── netbeheer.py    # Congestiekaart
│   │   └── knmi.py         # Zondata voor PV schatting
│   ├── calculators/        # Berekeningen
│   │   ├── tax.py          # Energiebelasting
│   │   ├── subsidy.py      # EIA/MIA/ISDE
│   │   └── grid_costs.py   # Netbeheerkosten
│   └── data/               # Statische data
│       ├── acm_tarieven.py # ACM tarieven 2025
│       └── postcode_mapping.py # Postcode → netbeheerder
└── models/                 # Pydantic data models
    └── enrichment.py       # Types voor verrijking
```

## 🔧 Lokaal Draaien

```bash
# Clone repo
git clone https://github.com/jouw-username/battery-optimizer-api.git
cd battery-optimizer-api

# Maak virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Installeer dependencies
pip install -r requirements.txt

# Start de server
uvicorn app.main:app --reload --port 8000
```

## 🌐 Environment Variables

| Variable | Beschrijving | Verplicht |
|----------|--------------|-----------|
| `PORT` | Poort voor de server | Nee (default: 8000) |
| `ENTSOE_API_KEY` | ENTSO-E API key voor stroomprijzen | Nee (fallback) |
| `TENNET_API_TOKEN` | TenneT API token voor onbalansprijzen | Nee (fallback) |

## 📊 Data Bronnen

- **ACM** - Netbeheertarieven 2025
- **Belastingdienst** - Energiebelasting tarieven
- **RVO** - EIA/MIA subsidie regelingen
- **ENTSO-E** - Day-ahead stroomprijzen
- **TenneT** - Onbalansprijzen
- **Netbeheer NL** - Congestiekaart
- **KNMI** - Zondata voor PV schatting

## 🛠️ Technische Stack

- **FastAPI** - Web framework
- **Pydantic** - Data validatie
- **httpx** - Async HTTP client
- **structlog** - Gestructureerde logging
- **Railway** - Hosting

## 📝 Notities voor Bart

De belangrijkste bestanden om te begrijpen:
1. `app/main.py` - Start hier, bekijk hoe de API opgebouwd is
2. `app/services/enrichment.py` - Kern van de data verrijking
3. `app/services/calculators/tax.py` - Hoe energiebelasting werkt
4. `app/services/calculators/subsidy.py` - Hoe EIA subsidie werkt

Alle bestanden hebben uitgebreide Nederlandse commentaren!
