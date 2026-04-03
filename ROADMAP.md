# Paint by Numbers – Python Backend Roadmap

## Projektziel

Ein Python-Backend, das Bilder automatisch in Malen-nach-Zahlen-Vorlagen umwandelt und diese über eine REST-API für eine iPhone App bereitstellt.

---

## Architektur

```
[Bild-Upload (Admin)] → [Bildverarbeitung] → [Storage] → [API] → [iPhone App]
```

---

## Phase 1: Bildverarbeitung (Kern-Algorithmus)

Ziel: Ein Python-Script, das ein Eingabebild in eine Malen-nach-Zahlen-Vorlage umwandelt.

### Schritte:

1. **Bild einlesen & vorbereiten**
   - Resize auf sinnvolle Maximalgröße (z. B. 1000px Breite)
   - In RGB konvertieren

2. **Farbreduktion via K-Means Clustering**
   - Alle Pixel als Farbvektoren behandeln
   - K-Means mit k=10–20 Farben (konfigurierbar)
   - Jeden Pixel der nächsten Cluster-Farbe zuweisen

3. **Regionenerkennung**
   - Zusammenhängende Flächen gleicher Farbe finden (Connected Components)
   - Sehr kleine Regionen entfernen oder zusammenführen (Rauschen eliminieren)

4. **Kantenlinie erzeugen**
   - Grenzen zwischen Regionen als schwarze Linien zeichnen
   - Ergebnis: schwarze Umrisslinien auf weißem Hintergrund (das Ausmalbild)

5. **Regionen nummerieren**
   - Jede Farbe bekommt eine Nummer (1–N)
   - Nummer wird zentriert in die jeweilige Region gezeichnet

6. **Output erzeugen**
   - `outline.png` – das Ausmalbild (weiß + schwarze Linien + Zahlen)
   - `preview.png` – das fertig ausgemalte Referenzbild
   - `palette.json` – Farb-Mapping: `{"1": "#FF6B6B", "2": "#4ECDC4", ...}`

### Bibliotheken:
- `opencv-python` – Bildverarbeitung, Kantenerkennung
- `scikit-learn` – K-Means Clustering
- `numpy` – Array-Operationen
- `Pillow` – Bild-I/O und Zeichnen

### Testlauf:
```bash
python generate.py --input meinbild.jpg --colors 15 --output ./output/
```

---

## Phase 2: FastAPI REST-Backend

Ziel: Die Bildverarbeitung als API verfügbar machen.

### Endpoints:

| Method | Path | Beschreibung |
|--------|------|--------------|
| `GET` | `/templates` | Liste aller Vorlagen |
| `GET` | `/templates/{id}` | Details + URLs einer Vorlage |
| `GET` | `/templates/{id}/outline` | Ausmalbild (PNG) |
| `GET` | `/templates/{id}/preview` | Vorschau (PNG) |
| `GET` | `/templates/{id}/palette` | Farbpalette (JSON) |
| `POST` | `/admin/upload` | Neues Bild hochladen & verarbeiten |

### Datenmodell (SQLite via SQLModel):
```python
class Template(SQLModel, table=True):
    id: int
    name: str
    created_at: datetime
    color_count: int
    outline_path: str
    preview_path: str
    palette_path: str
```

### Projektstruktur:
```
PictureGeneratePaintbyNumber/
├── main.py              # FastAPI App
├── generate.py          # Bildverarbeitungs-Algorithmus
├── models.py            # Datenbank-Modelle
├── database.py          # DB-Verbindung
├── requirements.txt     # Abhängigkeiten
├── storage/             # Generierte Dateien
│   └── templates/
│       └── {id}/
│           ├── outline.png
│           ├── preview.png
│           └── palette.json
└── Dockerfile           # Für Railway-Deployment
```

---

## Phase 3: Deployment auf Railway.app

1. GitHub-Repo erstellen und Code pushen
2. `Dockerfile` vorbereiten (Python 3.11 + alle Dependencies)
3. Bei [Railway.app](https://railway.app) einloggen (GitHub-Login möglich)
4. "New Project" → "Deploy from GitHub Repo" → Repo auswählen
5. Umgebungsvariablen setzen (z. B. `SECRET_KEY` für Admin-Uploads)
6. Railway generiert automatisch eine öffentliche URL → diese in die iPhone App eintragen

### Dockerfile (Grundgerüst):
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Reihenfolge für Claude Code

Bitte in dieser Reihenfolge implementieren:

1. `generate.py` – Bildverarbeitungs-Algorithmus mit Testlauf
2. Einen konkreten Test mit einem echten Bild durchführen und Ergebnis prüfen
3. `main.py` – FastAPI App mit allen Endpoints
4. `models.py` + `database.py` – SQLite Datenbankanbindung
5. `requirements.txt` + `Dockerfile` – Deployment-Vorbereitung
6. Integrations-Test: Bild hochladen via API, Ergebnis prüfen

---

## Qualitätsziele

- Farbreduktion soll natürlich wirken (keine harten Farbsprünge)
- Regionen sollen groß genug sein zum Ausmalen (Mindestgröße konfigurierbar)
- Zahlen sollen gut lesbar sein (Schriftgröße abhängig von Regionengröße)
- API-Antwortzeiten unter 200ms für alle GET-Requests
- Upload + Verarbeitung darf ruhig 10–30 Sekunden dauern (async)
