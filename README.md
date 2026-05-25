# MISS - model trybuny w Pygame

Prototyp pokazuje caly stadion zlozony z mapy pojedynczej trybuny zapisanej w JSON-ie. Tlum agentow porusza sie automatycznie do tuneli ewakuacyjnych, unikajac scian i innych agentow. Czerwone podswietlenie pokazuje lokalne zageszczenie, dzieki czemu widac miejsca powstawania korkow.

## Uruchomienie

```powershell
.\.venv\Scripts\python.exe main.py
```

Sprawdzenie konfiguracji bez otwierania okna:

```powershell
.\.venv\Scripts\python.exe main.py --check-config
```

## Struktura kodu

- `main.py` / `app.py` - wejscie aplikacji i glowna petla Pygame.
- `config_loader.py` i `layout_builder.py` - wczytywanie JSON-a oraz skladanie pelnego stadionu z segmentow trybun.
- `stadium.py`, `crowd.py`, `drawing.py`, `ui.py` - geometria stadionu, symulacja agentow, rysowanie i panel sterowania.

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

Sekcja `layout.full_stadium` sklada pelny stadion z tej samej mapy trybuny: domyslnie 4 kopie sa na gorze, 4 odbite kopie na dole, a po 3 obrocone kopie na lewym i prawym boku. Narozniki sa wypelniane dwoma trojkatnymi przedluzeniami sasiednich sektorow, dzieki czemu rzedy obiegaja boisko bez pustych pol. Rysowanie trybun nadal odbywa sie przez style kafelkow z JSON-a.

## Symulacja tlumu

Parametry agentow ustawisz w sekcjach `agent` i `crowd`.

- `agent.radius` - promien pojedynczej osoby.
- `agent.speed` - bazowa predkosc marszu.
- `crowd.count` - liczba agentow na pojedynczy segment trybuny, gdy `layout.full_stadium.scale_crowd_by_segments` jest wlaczone.
- Ekran startowy ogranicza liczbe agentow do liczby unikalnych miejsc startowych w aktualnym ukladzie stadionu.
- Agenci startuja rownomiernie na przejsciach trybuny, z pominieciem schodow i tunelu.
- `crowd.personal_space` - dystans, ktory agent probuje utrzymac od innych.
- `crowd.repulsion_strength` - sila odpychania miedzy agentami.
- `crowd.wall_repulsion_strength` - sila odpychania od scian.
- `crowd.collision_iterations` - liczba iteracji rozdzielania kolizji agentow; nizsza wartosc jest szybsza na duzym stadionie.

Sterowanie:

- Ekran startowy - ustaw liczbe i podstawowe parametry agentow oraz wybierz scenariusz.
- `Space` - pauza / wznowienie.
- `Esc` - zamknij symulacje.

## Scenariusze i wyniki

Gotowe eksperymenty znajduja sie w katalogu `scenarios/` i mozna je wybrac na ekranie startowym:

- pozar w sektorze, ktory wylacza jego wyjscie i kieruje tlum do innych bram,
- lokalna panika powodujaca chaotyczne decyzje trasy i mniej przewidywalny ruch,
- atak bombowy, po ktorym pobliscy agenci natychmiast uciekaja od miejsca zdarzenia, a wyjscie sektora jest niedostepne.

Kazde uruchomienie symulacji zapisuje jeden plik CSV w katalogu `results/`. Plik jest rozdzielany srednikami i zawiera po jednym wierszu na probke czasu: podstawowe parametry przebiegu, liczby aktywnych i ewakuowanych agentow, gestosc, predkosc oraz stan scenariusza. Po zakonczeniu kazdy wiersz zawiera takze finalne podsumowanie czasow ewakuacji, co ulatwia porownywanie i wizualizacje przebiegow. Przebieg konczy sie po ewakuacji wszystkich agentow, po osiagnieciu limitu czasu albo po zamknieciu symulacji.

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
