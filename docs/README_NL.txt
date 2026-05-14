MxSim Racing OBS Overlay v2.0.12

Een Windows-programma dat een lokale OBS Browser Source overlay maakt voor de MxSim Racing league ranking pagina.

Snel starten
1. Start MxSimRacingOBSOverlay.exe.
2. Vul een ridernaam of deel van de ridernaam in.
3. Laat de scrape URL op https://mxsimracing.com/league staan, tenzij de leaguepagina verandert.
4. Klik op Search / scrape.
5. Voeg in OBS een Browser Source toe met URL: http://localhost:3000
6. Zet de Browser Source op 320 x 150 en FPS 10 of 15.

Standaardinstellingen
- Scrape interval: 3 minuten
- OBS refresh: elke 5 seconden
- Lokale poort: 3000
- Low-lag mode: de browser opent alleen tijdens scraping en sluit daarna automatisch.
- Vensterbranding (favicon + headerafbeelding) wordt online van mxsimracing.com gedownload; ongeveer één dag gecached.

Probleemoplossing
- Als poort 3000 al in gebruik is, sluit oudere draaiende versies van het programma.
- Als een rider niet gevonden wordt, probeer een korter deel van de naam.
- Het programma laadt automatisch meer rankingregels tijdens het zoeken.
- Overlaydata wordt lokaal opgeslagen en via een lokaal JSON-bestand aan OBS gegeven voor betrouwbaarheid.

Build
Run eerst BUILD_PORTABLE_EXE.bat. Run daarna BUILD_INSTALLER.bat om de installer in de release-map te maken.
