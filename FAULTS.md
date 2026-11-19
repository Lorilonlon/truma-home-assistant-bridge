# Gerätemeldungen und Benachrichtigungen

Die Bridge liest Warnungen und Störungen getrennt von Verbindungsproblemen und
nicht bestätigten Steuerbefehlen. Unbekannte Fehlertexte werden unverändert
angezeigt, nicht durch vermutete Ursachen ersetzt. Die Meldung allein ist keine
Diagnose oder Freigabe zum Weiterbetrieb.

## Home Assistant

- `sensor.truma_inet_meldungen`: aktueller Überblick, aktive Meldungen, Herkunft,
  Zeitpunkt, Aktualität und die letzten 30 Ereignisse als Attribute.
- `sensor.truma_inet_meldeereignis`: persistente Ereigniskennung, Nachricht und
  Zeitpunkt für Benachrichtigungen. Unveränderte Meldungen erzeugen keine neue
  Kennung. Mehrere Änderungen eines Abfragezyklus werden zusammengefasst.
- `button.truma_inet_meldungen_gesehen`: ausschließlich lokale Bestätigung.
  Ein Gerätefehler bleibt bestehen, bis das Gerät ihn nachweislich nicht mehr
  meldet. Ein vergangener fehlgeschlagener Steuerauftrag wird als gesehen
  archiviert; er wird nicht automatisch erneut ausgeführt.
- `binary_sensor.truma_inet_verbindung`: Verfügbarkeit getrennt überwachen.

Zusätzlich zu `dashboard/camper-inet-card.js` die Ressource
`dashboard/camper-inet-fault-card.js` als JavaScript-Modul registrieren. Die
Beispielkonfiguration `dashboard.json` enthält die Meldungskarte. Bei einer
bestehenden Installation nur diese Karte ergänzen, kein bestehendes Dashboard
komplett ersetzen.

Handy-Benachrichtigungen werden bewusst in Home Assistant eingerichtet. Die
Bridge enthält keine Handykennungen oder Push-Zugangsdaten. Eine Automation
sollte neue Ereigniskennungen mit einem persistenten Texthelfer vergleichen,
die Nachricht an das ausgewählte Companion-App-Gerät senden und erst nach
erfolgreicher Übergabe die Kennung speichern. Ein gleichbleibender Notification-
Tag verhindert viele übereinanderliegende Meldungen. Der Link öffnet das
Klima-Dashboard; „Gesehen“ und tatsächliche Gerätequittierung bleiben getrennt.
Bei Neustart denselben Vergleich durchführen. Ein Verbindungsalarm sollte erst
nach mindestens zwei Minuten fehlen und bei bestätigter Rückkehr einmalig
aktualisiert werden. Ein persistenter Merker verhindert Wiederholungen.

Die Übergabe an den Push-Dienst beweist noch nicht die Zustellung oder das Lesen
am Handy. Bei einem Ausfall von Home Assistant, Internet oder Push-Dienst ist
dieser Meldeweg nicht verfügbar. Während HA offline ist, bleibt das letzte
Ereignis per MQTT erhalten; ältere Übergänge stehen im begrenzten Journal,
werden jedoch nicht einzeln als Push nachgeliefert.

## Protokoll und Grenzen

Nachgewiesene App-Meldung: Charakteristik `00000108` im jeweiligen Geräte-Service.
UUID-Endung jeweils `-0004-0001-0000-0000fe088214`:

| Service-Präfix | Gerät |
| --- | --- |
| `00010000` | Heizung |
| `00030000` | Bedienpanel |
| `00020000`, `00021000` | Klimaanlagen 1 und 2 |
| `00040000` | Schaudt |

Leere oder vollständig nullgefüllte Daten bedeuten keine Meldung. Sonst werden
abschließende Nullbytes entfernt: Erstes Byte `1` = Warnung, `2` = Störung,
unbekannte Werte bleiben als unbekannte Meldung sichtbar. Die verbleibenden
Bytes bilden den Originaltext (Zeichencodes, kein numerisches UInt16-Feld).
Ungültige Kontrollzeichen werden als nicht auswertbare Abfrage behandelt.
Die Gerätezuordnung stammt aus dem Service, nicht aus dem letzten Buchstaben
des Textes. Fehlende Gerätekanäle gelten als nicht unterstützt, nicht als gesund.

Die zusätzlichen Heizungsattribute `0001000B`/`0001000C` sind in der Original-App
als Fehlercode und Fehlerklasse benannt. Deren vollständige Aktivitätssemantik
ist nicht belegt; insbesondere bedeutet die Klasse „warning“ allein keine
aktive Warnung. Die Bridge leitet daraus keinen zusätzlichen Alarm ab.

Bei Lesefehler, Verbindungsabbruch oder Neustart bleibt eine bekannte Störung
als ungeprüfter letzter Stand erhalten. Erst ein erfolgreiches Lesen ohne
Meldung löst sie auf. Die lokale Historie ist auf 30 Übergänge begrenzt und keine
lückenlose Sicherheitsaufzeichnung. Polling kann sehr kurze Meldungen verpassen.

**Wie in der Truma iNet System App lässt sich eine Heizungsstörung über die klassische iNet-Box auch in Home Assistant nicht aus der Ferne zurücksetzen.** Für einen passenden Bluetooth-Quittierbefehl gibt es noch
keinen belastbaren Nachweis. Der App-Serializer dieses Meldungsattributs ist
nicht implementiert. Auch die nachverfolgten Aktionen der App-Meldungsansicht
öffnen Meldungen und Hilfelinks, keinen belegten Geräte-Reset. Deshalb werden
weder ein Reset-Button noch geratenes Schreiben oder automatische
Quittierwiederholungen angeboten.
Gerät und Herstelleranleitung vor Ort prüfen; erforderliche Quittierung am
Bedienpanel erst nach Beseitigung der Ursache.

Die zusätzliche Untersuchung der App unterscheidet drei andere Funktionen:
Ein App-Neustart startet nur die Android-Anwendung, Bluetooth-Abschaltung
beendet deren Verbindung, und ein Neustart der iNet-Box wird im Ablauf einer
Firmwareinstallation verwendet. Letzterer ist kein belegter allgemeiner
Reboot und wird nicht außerhalb dieses Updateablaufs ausgeführt. Auch für
das vollständige Ausschalten des CP-plus-Panels durch langes Drücken wurde
in den untersuchten App-Definitionen kein entsprechender Fernbefehl belegt.
Diese begrenzte Suche beweist nicht, dass die Firmware keinen solchen Befehl hat.

### Optional: Heizung neu starten

`dashboard/heater-restart-script.json` enthält eine eigenständige HA-Skriptkonfiguration.
Über die HA-Konfigurations-API als `truma_heizung_neu_starten` anlegen; bei
abweichenden Entity-IDs die Referenzen anpassen. Die Meldungskarte zeigt dann
den Button **Heizung neu starten** (`restart_entity` ist konfigurierbar).
Das Skript benötigt die Timer- und Meldungssensoren dieser Beta-Version.

Nach ausdrücklicher Bestätigung `cause_resolved: true` werden Warmwasser und
Raumheizung einmal ausgeschaltet. Auf bestätigtes Aus folgt eine Pause
von drei Minuten; sie ist ein gewählter Testwert und kein Nachweis für abgeschlossenen Gerätenachlauf
oder ausreichende Abkühlung. Danach werden die vorherigen Betriebswerte
schrittweise wiederhergestellt und die Meldungen frisch ausgelesen.
Die Ursache muss vorher behoben sein; Herstelleranweisungen gelten weiterhin.
Dies ist **kein elektrischer Neustart und kein nachgewiesener Fehlerreset**.

Gleichzeitige Aufrufe werden abgewiesen, ein aktiver oder unbekannter Gerätetimer
verhindert den Ablauf. Jeder Schritt benötigt eine Rückmeldung. Bei Abbruch
können Werte teilweise verändert bleiben; es gibt weder Wiederholungen noch
automatisches Fortsetzen nach HA-Neustart. Während des Ablaufs keine parallelen
Bedienbefehle senden: Das HA-Skript sperrt andere Steuerwege nicht vollständig.
Deshalb erfolgt die Wiederherstellung bewusst einzeln mit Rückmeldungsprüfung,
nicht gleichzeitig über eine Szene.

Das Ergebnis erscheint als dauerhafte HA-Benachrichtigung. Optional kann
`variables.notify_service` auf die eigene `notify.mobile_app_…`-Aktion gesetzt
werden; das veröffentlichbare Beispiel enthält keinen persönlichen Empfänger.
Die Benachrichtigungslinks bei einem anderen Dashboard ebenfalls anpassen.

Getestet: synthetische Warnungen/Störungen, unbekannte Werte, Lesefehler,
Neustart, Wiederauftreten, Begrenzung und lokale Bestätigung ohne Gerätezugriff.
An einer iNet-Box wurde der meldungsfreie Zustand von Heizung und Bedienpanel
ausgelesen. Eine später aufgetretene W17H-Warnung wurde live ausgelesen;
„Gesehen“ ließ sie korrekt aktiv. Ein einmaliger Betriebswechsel nach vom
Benutzer bestätigter Ursachenbehebung stellte 19 °C/Eco/Warmwasser niedrig
wieder her, **löschte W17H aber nicht**. Auch ein zweiter, ausdrücklich
angeforderter Versuch mit 180 statt zehn Sekunden Pause ließ W17H bestehen.
Die Warnung war während der Ausschaltphase direkt über Bluetooth lesbar;
es handelte sich nicht bloß um einen stehengebliebenen HA-Anzeigetext.
Die zusätzlichen Fehlercode-/Fehlerklassenfelder lieferten auf dieser Box
leere Daten und wurden nicht als Entwarnung interpretiert.
Die weiterhin aktive Warnung wurde anschließend korrekt gemeldet.
Daraus folgt keine Reset-Wirkung für andere
Warnungen oder Störungen; ein Gerätefehler wurde nicht absichtlich erzeugt.
Klimaanlagen- und Schaudt-Kanäle sind nicht an echter Hardware validiert.
