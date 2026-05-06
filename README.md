# MISS - model trybuny w Pygame

Prototyp pokazuje pojedyncza trybune stadionu jako siatke kafelkow. Tlum agentow porusza sie automatycznie do tunelu ewakuacyjnego, unikajac scian i innych agentow. Czerwone podswietlenie pokazuje lokalne zageszczenie, dzieki czemu widac miejsca powstawania korkow.

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

`P` i `D` sa cienkimi przeszkodami rysowanymi wewnatrz pelnego kafelka. Dzieki temu sciany moga wygladac jak barierki, ale ruch agentow nadal liczy sie na stabilnej siatce o rownych wymiarach.

## Symulacja tlumu

Parametry agentow ustawisz w sekcjach `agent` i `crowd`.

- `agent.radius` - promien pojedynczej osoby.
- `agent.speed` - bazowa predkosc marszu.
- `crowd.count` - liczba agentow.
- Agenci startuja rownomiernie na przejsciach trybuny, z pominieciem schodow i tunelu.
- `crowd.personal_space` - dystans, ktory agent probuje utrzymac od innych.
- `crowd.repulsion_strength` - sila odpychania miedzy agentami.
- `crowd.wall_repulsion_strength` - sila odpychania od scian.

Sterowanie:

- Ekran startowy - ustaw liczbe agentow i uruchom symulacje.
- `Space` - pauza / wznowienie.
- `Esc` - zamknij symulacje.

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
