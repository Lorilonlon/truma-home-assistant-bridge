# Änderungen

## Bridge 0.1.9-beta.6

- HA-Timerformular mit leeren Entwürfen, gemeinsamem Speichern und acht persistenten Timerplätzen. Einmalig/täglich, optionale Endzeit mit frischem Vorzustand und bestätigter Wiederherstellung. Überschneidungen verlangen ausdrückliche Zustimmung; spätere Starts verhindern ältere Rückstellungen. Anzeige unterscheidet HA-Vormerkung von bestätigten Truma-Werten. Neue Ablauf- und Browserprüfungen; der echte Zeitablauf bleibt noch vor Ort zu beobachten.
- Optionales HA-Skript und Dashboard-Button „Heizung neu starten“: einmaliger, manuell bestätigter Betriebswechsel mit drei Minuten Pause, Wiederherstellung und Rückmeldung. Kein behaupteter Fehlerreset; bei realen W17H-Tests mit zehn und 180 Sekunden Pause blieb die Warnung aktiv und wurde gemeldet.
- Korrigiert: Die bisherige gemeinsame Drei-Sekunden-Frist konnte gültige Heizbefehle schon während der Vorprüfung verwerfen. Wartende Befehle sind jetzt auf fünf Sekunden begrenzt; angenommene Befehle haben separat maximal zwölf Sekunden für Prüfung, Schreiben und Rückmeldung. Verbindungswechsel, fehlende Bestätigung und Zeitüberschreitung verhindern weiterhin Erfolgsmeldungen; keine automatische Wiederholung.
- 87 Softwaretests einschließlich langsamer Antworten, abgelaufener Warteschlange, hängender Abfrage und verlorener Antwort nach einem Schreibzugriff bestanden.
- Gerätewarnungen und Störungen werden aus dem belegten App-Meldungskanal gelesen; Gerätezuordnung, Originaltext, Aktualität und die letzten 30 Ereignisse bleiben nachvollziehbar.
- Fehlgeschlagene Steuerbefehle erhalten ein eigenes Ereignis. „Gesehen“ bestätigt nur die Meldung, niemals die Heizung. Ein Geräte-Reset bleibt mangels belegtem Protokoll deaktiviert.
- Separate Meldungskarte und MQTT-Ereignissensor für Handy-Benachrichtigungen. Details und Testgrenzen in `FAULTS.md`.
- Echte tägliche Truma-Zeitschaltuhr mit separaten Zeiten, Raumtemperatur, Gebläse und Warmwasser sowie eigener Dashboard-Karte vorbereitet.
- Timer wird regelmäßig ausgelesen; Änderungen am Bedienpanel werden zurückgemeldet. Bearbeiten aktiviert ihn nicht automatisch.
- Timer-Schreibzugriff standardmäßig gesperrt. 76 Softwaretests sowie Schreiben und Zurücklesen bei ausgeschaltetem Timer an einer Combi 6 bestanden; CP-plus-Abgleich und Ausschalten über HA am 19.11.2026 bestätigt (06:30–08:20, 19 °C, Eco, Warmwasser aus). Der vollständige zeitgesteuerte Ablauf am Gerät bleibt offen.
- Zusätzliche Prüfungen vor Timerbefehlen erkennen zwischenzeitliche Änderungen, veraltete Befehle und Verbindungswechsel.
- MQTT-Erkennung verwendet `default_entity_id`; bestehende eindeutige Kennungen bleiben erhalten.
- Fehlende Timer-Auswahlwerte werden sauber als unbekannt gemeldet. Einzelne Änderungen lesen nur die betroffenen Timerfelder doppelt; veraltete Timerbefehle vor dem Schreiben setzen die Heizungsverbindung nicht auf gestört.

## Bridge 0.1.8

- Begrenzte lokale Verbindungshistorie mit Zustandswechseln, Fehlertypen, Systemdruck und Fünf-Minuten-Status.
- ZIP-Download der Diagnosehistorie ausschließlich über die geschützte Bridge-Weboberfläche.
- Zeitüberschreitungen werden als TimeoutError angezeigt, statt mit leerer Fehlermeldung.
- Keine Funkpakete, Schlüssel, Steuerbefehle oder automatischen Neustarts durch die Diagnose.

## Bridge 0.1.7

- Gemessene Wassertemperatur als eigener Sensor und in der Warmwasserkachel.
- Beschriftete Kacheln: Im Raum, Zieltemperatur, Wassertemperatur und Warmwasserstufe.
- Ausgeschaltete Heizung kennzeichnet den gespeicherten Zielwert als vorgemerkt.
- Sensorvorlagen verarbeiten auch ältere Statusmeldungen ohne neue Messfelder.

## Bridge 0.1.6 / Kompatibilität 0.1.2

- Raumtemperatur und Versorgungsspannung als optionale, reine Lesesensoren.
- Gemessene Temperatur auch als Klima-Istwert mit einer Nachkommastelle und in der Einrichtungsoberfläche.
- Regelmäßige Messwertabfragen werden durch häufige Steuerbefehle nicht verdrängt.
- Messwertausfall liefert unbekannt, ohne die Heizungssteuerung zu sperren.
- Persönliche Geräteadresse durch Konfiguration ersetzt, leere Erstinstallation startet nicht versehentlich gegen ein fremdes Gerät.
- MIT-Lizenz, eigene Protokollnotizen und Installationshinweise ergänzt.
- Tests für Sensoren und acht Linux-C-Fälle der konfigurierbaren Verzögerung.

## Bridge 0.1.4

- Befehle nach langsamem Auslesen erneut auf Aktualität prüfen.
- Fehlgeschlagene MQTT-Veröffentlichungen bleiben wiederholbar.
- aiohttp auf 3.14.3 aktualisiert.

## Bridge 0.1.3

- Sollwertwahl bei ausgeschalteter Heizung bleibt lokal vorgemerkt.

## Bridge 0.1.2

- Warmwasser Aus und Boost ergänzt; reale Betriebsprobe noch offen.
