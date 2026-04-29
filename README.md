# MISS - model trybuny w Pygame

Prototyp pokazuje pojedyncza trybune stadionu jako siatke kafelkow. Agent porusza sie po korytarzach i schodach za pomoca WSAD, a sciany i rzedy blokuja ruch.

## Uruchomienie

```powershell
.\.venv\Scripts\python.exe main.py
```

Sprawdzenie konfiguracji bez otwierania okna:

```powershell
.\.venv\Scripts\python.exe main.py --check-config
```

## Mapa

Glowny plik konfiguracyjny to `stadium_config.json`. Najwazniejsza czesc to `layout.map`.

- `.` - przejscie / korytarz
- `#` - sciana pelnej kratki
- `P` - pionowa sciana
- `D` - pozioma sciana
- `S` - schody
- `E` - wyjscie ewakuacyjne
- `T` - tunel
- `A` - start agenta

`P` i `D` sa sciesnione: `P` zweza cala kolumne, a `D` obniza caly wiersz. Dzieki temu nie ma pustej czesci kratki obok cienkiej sciany.

Grubosc scian ustawisz w `tiles`:

```json
"P": {
  "name": "pionowa sciana",
  "solid": true,
  "edges": ["P"],
  "visual_width_ratio": 0.35
}
```

```json
"D": {
  "name": "pozioma sciana",
  "solid": true,
  "edges": ["D"],
  "visual_height_ratio": 0.35
}
```
