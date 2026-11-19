<img align="right" src="https://raw.githubusercontent.com/Lorilonlon/truma-inet-dashboard/9d673df6d196af87479304187b3392f84646790e/images/wohnmobil-heizung.png" alt="Wohnmobil mit zwei Wärmewellen" width="80" height="80">

# Truma iNet Bridge für Home Assistant

[English](README.md)

Mit der Bridge steuerst du Raumheizung und Warmwasser über deine klassische **Truma iNet-Box** direkt aus Home Assistant. Die Bridge läuft lokal, verbindet sich per Bluetooth mit der Box und stellt Bedienelemente und Sensoren über MQTT bereit. Ich habe sie mit meiner Truma Combi 6 getestet. Das iNet-X-Protokoll wird nicht unterstützt.

> [!WARNING]
> Die Software ist experimentell und steuert eine echte Heizung und Warmwasseranlage. Die Nutzung erfolgt auf eigene Gefahr. Falsche Messwerte, Verbindungsabbrüche oder unerwartete Schaltvorgänge können zu Verletzungen, Brand, Überhitzung oder Frostschäden führen. Teste Änderungen vor Ort, beachte die Herstelleranleitung und halte das Bedienteil zugänglich. Verlass dich beim Frostschutz nicht allein auf die Bridge. Verhält sie sich unerwartet, stoppe die Bridge und bediene die Anlage vor Ort nach Herstelleranleitung. Es gilt die MIT-Lizenz. Zwingende gesetzliche Haftung bleibt unberührt. [Sicherheit und Haftung](LEGAL.md#sicherheit-und-haftung)

## Heizung, Warmwasser und Dashboard

Du kannst die gewünschte Raumtemperatur einstellen, die Lüfterstufe Eco oder High wählen und das Warmwasser auf Aus, Niedrig, Hoch oder Boost stellen. Änderst du die Zieltemperatur bei ausgeschalteter Raumheizung, speichert die Bridge sie für das nächste Einschalten. Das Dashboard zeigt die gemessene Raum- und Wassertemperatur, die von der Box bestätigten Einstellungen und den Verbindungsstatus.

Die Versorgungsspannung steht als eigener Sensor zur Verfügung. Sie wird an der iNet-Box gemessen und kann von der Anzeige deines Batteriemonitors abweichen. Fehlende oder unplausible Messwerte erscheinen als „Unbekannt“. Die Rückmeldung der Box bestätigt die Einstellung. Ob der Brenner gerade läuft, lässt sich daraus nicht ablesen.

## Dashboard-Vorschau

Die Mobilansicht kombiniert das Thermostat-Drehrad von Home Assistant mit den Truma-Karten. Der grüne Timer zeigt von der Box bestätigte Einstellungen. Alle Messwerte sind Beispieldaten, Zeitangaben sind ausgeblendet.

<img src="https://raw.githubusercontent.com/Lorilonlon/truma-inet-dashboard/c3bf9088972b62625f0b067bf60762f61a051561/images/heating-water.png" alt="Mobile Ansicht mit Drehrad, Heizungs- und Warmwassersteuerung sowie bestätigtem Timer" width="380">

<details>
<summary>Timerformular und Beispielmeldung ansehen</summary>

<img src="https://raw.githubusercontent.com/Lorilonlon/truma-inet-dashboard/c3bf9088972b62625f0b067bf60762f61a051561/images/timer.png" alt="Timerformular mit leerem Feld für Datum und Startzeit" width="360">
<img src="https://raw.githubusercontent.com/Lorilonlon/truma-inet-dashboard/c3bf9088972b62625f0b067bf60762f61a051561/images/faults.png" alt="Beispielmeldung für eine unbestätigte Zieltemperatur" width="360">

</details>

## Timer

- **Zeitpläne in Home Assistant.** Du kannst bis zu acht einmalige oder tägliche Timer vormerken. Wähle Datum, Uhrzeit, Raumtemperatur, Lüfterstufe und Warmwasser und speichere das Formular mit einem Klick. Vorgemerkte Timer lassen sich bearbeiten. Wählst du eine Endzeit, stellt Home Assistant am Ende die Einstellungen wieder her, die unmittelbar vor dem Start galten. Ohne Endzeit bleiben die neuen Einstellungen bestehen.
- **Überschneidungen.** Überschneidet sich ein neuer Timer mit einem vorhandenen, bittet dich das Dashboard vor dem Speichern um Bestätigung. Der später startende Timer übernimmt. Die Endzeit des älteren Timers kann seine Einstellungen nicht zurücksetzen. Im Dashboard siehst du, ob ein Timer in Home Assistant vorgemerkt ist oder ob die Box die Einstellungen bereits bestätigt hat. Abgeschlossene einmalige Timer verschwinden nach 24 Stunden aus der Liste.
- **Ausführung.** Zur Ausführung müssen Home Assistant und die Bluetooth-Verbindung zur Box verfügbar sein. Bleibt die Bestätigung der Box auch nach mehreren Versuchen aus, meldet Home Assistant den Fehler. Richtest du eine Handy-Benachrichtigung ein, bekommst du die Meldung auch unterwegs. [Zeitplaner und Dashboard einrichten](dashboard/TIMER.md)
- **Gerätetimer am CP plus.** Der tägliche Timer der Truma speichert eine Start- und eine Endzeit. Du kannst ihn über die Bridge auslesen. Zum Ändern musst du den Schreibzugriff mit `allow_timer_control` freigeben. Ich habe bei ausgeschaltetem Gerätetimer die Endzeit in Home Assistant geändert und die Einstellungen direkt am CP plus überprüft. Das Panel zeigte **06:30–08:20 Uhr, 19 °C, Eco, Warmwasser aus**. Anschließend habe ich die ursprüngliche Endzeit wiederhergestellt und über die Bridge zurückgelesen. Ein vollständiger zeitgesteuerter Start und Stopp durch das CP plus steht als Test noch aus. [Tests und Grenzen des Gerätetimers](TIMER_PROTOCOL.md)

## Warnungen und Heizungsstörungen

**Wie in der Truma iNet System App kannst du auch mit Home Assistant eine Heizungsstörung über die klassische iNet-Box nicht aus der Ferne zurücksetzen.** Das Dashboard zeigt die vom Gerät gemeldete Störung. Mit „Gesehen“ bestätigst du, dass du die Meldung in Home Assistant gelesen hast. Verlangt die Heizung eine Quittierung am CP plus, behebe die Ursache und folge vor Ort der Herstelleranleitung.

Über die Companion App kann Home Assistant neue Warnungen, Störungen und fehlgeschlagene Steuerbefehle an dein Handy weiterleiten. Dafür richtest du in Home Assistant eine Benachrichtigungsaktion ein. Die optionale Aktion „Heizung neu starten“ schaltet Heizung und Warmwasser aus und stellt anschließend die vorherigen Einstellungen wieder her. Bei meinen Tests blieb die Warnung W17H auch nach diesem Neustart bestehen. [Fehlermeldungen und Benachrichtigungen einrichten](FAULTS.md)

## Installation

1. Richte unter Home Assistant OS die MQTT-Integration und einen erreichbaren MQTT-Broker ein. [App-Repository zu Home Assistant hinzufügen](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FLorilonlon%2Ftruma-home-assistant-bridge). Wähle im App-Store **Camper Heater Bridge**. Home Assistant baut die App lokal aus dem Quellcode.
2. Trage die Bluetooth-Adresse deiner Box unter `box_address` ein, wähle den Adapter (meist `hci0`) und gib die MQTT-Verbindungsdaten an. TLS ist standardmäßig aktiviert. Falls du eine eigene Zertifizierungsstelle verwendest, hinterlege ihr öffentliches CA-Zertifikat. Der Bluetooth-Adapter muss BLE Peripheral Advertising und einen GATT-Server unterstützen. Ein gewöhnlicher ESPHome-Bluetooth-Proxy erfüllt diese Anforderungen nicht.
3. Schalte Bluetooth auf allen zuvor mit der Box gekoppelten Handys aus. Starte die Bridge, öffne ihre Weboberfläche, starte die Kopplung und drücke die Bluetooth-Taste an der iNet-Box. Prüfe zuerst die Messwerte. Aktiviere `allow_control`, sobald du die Anlage steuern möchtest. Für Zeitpläne in Home Assistant brauchst du keinen Schreibzugriff auf den Gerätetimer.
4. Installiere [Truma iNet Dashboard über HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=Lorilonlon&repository=truma-inet-dashboard&category=plugin) und lade die Browserseite neu. Falls die Karten in der Suche noch fehlen, folge der [Anleitung für ein benutzerdefiniertes Repository](https://github.com/Lorilonlon/truma-inet-dashboard/blob/main/README.de.md#einrichtung). Für eine manuelle Installation kopiere `dashboard/camper-inet-card.js` und `dashboard/camper-inet-fault-card.js` nach `/config/www/` und registriere beide Dateien unter `/local/` als JavaScript-Module. Übernimm die gewünschten Karten aus dem [Beispiel-Dashboard](dashboard.json) in deine Ansicht. Prüfe die Entitäts-IDs und passe den Einrichtungslink an deine installierte App an. Für den Zeitplaner installierst du zusätzlich die [Timer-Helfer, das Skript und die Automation](dashboard/TIMER.md).
5. Nutzt du bereits eine lokale Installation oder die frühere GitHub-Adresse, behalte beim Update den vorhandenen Eintrag bei. Ein anderer Repository-Präfix kann eine zweite Installation erzeugen. Sichere vor einem Wechsel die bisherigen Optionen und Daten und betreibe nur eine Bridge gleichzeitig. Eine Neuinstallation aus GitHub und eine Migration habe ich auf meiner Hardware noch nicht getestet.

## Wenn die Bluetooth-Verbindung ausfällt

Ein gekoppeltes Handy kann sich automatisch wieder mit der Box verbinden und dadurch die Verbindung für die Bridge belegen. Verliert Home Assistant den Kontakt, trenne die Handyverbindung und schalte Bluetooth vorübergehend auf **allen** zuvor gekoppelten Handys aus. Denk dabei auch an ein Zweithandy. Verbindet sich ein Handy immer wieder, das du für die Box nicht mehr brauchst, entferne die Kopplung auf diesem Handy. Möchtest du die Truma-App gezielt nutzen, gib die Box auf der Einrichtungsseite der Bridge vorübergehend für die Handy-App frei.

Schlägt die Kopplung weiterhin fehl, findest du Hinweise in der [Anleitung zur optionalen Bluetooth-Kompatibilitäts-App](truma_bluetooth_compat/README.md). Diese verzögert eine Sicherheitsanfrage an die konfigurierte Box um 800 Millisekunden. Dafür greift sie in den gemeinsamen Bluetooth-Dienst ein und benötigt Berechtigungen auf dem Host.

Zur Fehlersuche kannst du in der Weboberfläche ein lokales Verbindungsprotokoll herunterladen. Drei rotierende Dateien belegen zusammen rund 1,5 MiB. Sie enthalten Verbindungswechsel und regelmäßige Statusmeldungen und bleiben bei einem App-Neustart erhalten. Der Export enthält keine Bluetooth-Nutzdaten, Kopplungsschlüssel oder konfigurierten Zugangsdaten. Behandle ihn trotzdem vertraulich, da Zeitstempel und Betriebszustände Rückschlüsse auf deine Nutzung erlauben.

## Meine Erfahrungen und Hinweise zum Projekt

Ich nutze die Bridge seit über einem Monat im Alltag in meinem Wohnmobil. In dieser Zeit lief sie bei mir fehlerfrei. Bei mir läuft Home Assistant OS auf einem Raspberry Pi 4 mit einer klassischen iNet-Box (Hardware 1.3.0, Firmware 3.1.5) und einer Combi 6.

Ich habe dieses unabhängige Community-Projekt mit [Unterstützung von OpenAI Codex](AI_DISCLOSURE.md) entwickelt. Es besteht keine Verbindung zu Truma oder zum Home-Assistant-Projekt. [MIT-Lizenz](LICENSE) · [Hinweise zu Drittanbietern](THIRD_PARTY.md) · [Sicherheitsprobleme vertraulich melden](SECURITY.md)
