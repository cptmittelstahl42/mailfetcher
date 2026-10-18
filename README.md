# Mailfetcher

**Mailfetcher** ist ein leichtgewichtiges, robustes Python-Tool zum automatischen Abholen von E-Mails über **POP3** (z. B. von Strato) und der Weiterleitung an einen internen Mailserver (z. B. **Microsoft Exchange**) per **SMTP**.

Das Projekt nutzt ein dateibasiertes Queue-System (Warteschlange), um E-Mails auch bei Netzwerkunterbrechungen oder Serverausfällen verlustfrei und zuverlässig zu verarbeiten.

## Status

* **Projektstatus:** Release Candidate (v1.0.0-rc1)
* **Getestet mit:**
  * Debian 13
  * Microsoft Exchange Server 2019
  * Strato POP3
  * Python 3.13

Das Projekt befindet sich in aktivem Einsatz im Homelab-Betrieb und unterstützt Queue-Verarbeitung, Retry-Mechanismen, Admin-Benachrichtigungen und automatisierte Bereinigung von Zustellungsarchiven.

---

## Architektur & Funktionsweise

### Warteschlange (Queue)

Anstatt eine E-Mail direkt vom POP3-Server an den Exchange-Server durchzureichen, durchläuft jede Mail mehrere Ordner unter `/opt/mailfetcher/queue/`. So geht selbst bei einem Absturz oder Serverausfall keine Mail verloren.

```text
[ POP3 Server ] ──(Download)──> [ pending ] ──(In Bearbeitung)──> [ processing ]
                                                                        │
                                                     ┌──────────────────┴──────────────────┐
                                               (Erfolg)                                (Fehler)
                                                     ▼                                     ▼
                                               [ delivered ]                         [ pending ] (Retry)
                                                     │                                     │ (max_retries)
                                             (Löschung nach 30 Tage)                       ▼
                                                                                      [ failed ] ──> (Admin-Alert)
```

* **`queue/pending` (Wartend):** E-Mails werden per POP3 heruntergeladen, mit einem eindeutigen SHA256-Hash als Dateinamen (`.eml`) versehen und hier gespeichert. Falls konfiguriert, werden sie direkt danach auf dem POP3-Server gelöscht.
* **`queue/processing` (In Bearbeitung):** Vor dem Senden wird die Mail in diesen Ordner verschoben. Sollte das Skript während des Sendevorgangs abstürzen, bleibt die Datei hier greifbar.
* **`queue/delivered` (Zugestellt):** Nach erfolgreicher Zustellung via SMTP an den Exchange-Server wandert die Mail hierhin. Ein automatischer Aufräumprozess löscht Dateien in diesem Ordner nach 30 Tagen.
* **`queue/failed` (Fehlgeschlagen):** Schlägt die Zustellung fehl, erhält die Datei ein Retry-Suffix (z. B. `.retry1`). Sie wandert zurück nach `pending` und wird beim nächsten Durchlauf erneut versucht. Erst wenn das Limit `max_retries` erreicht ist, wandert sie nach `failed` und eine Warnmeldung wird per E-Mail an den Admin gesendet.

---

## Features & Schutzmechanismen

* **Duplikatschutz:** Nachrichten werden anhand ihres Inhalts gehasht (SHA256). Bereits verarbeitete Mails werden nicht doppelt gequeut.
* **Prozess-Sperre (File Locking):** `fcntl` verhindert, dass sich parallele Skriptaufrufe (z. B. bei kurzen Cronjob-Intervallen) gegenseitig blockieren oder Mails doppelt verarbeiten.
* **Automatische Log-Rotation:** Die Log-Datei wächst nicht unendlich, sondern wird automatisch rotiert (max. 5 MB pro Datei, 5 Backups).
* **Retry & Admin-Alerts:** Wiederholungsversuche bei temporären Serverstörungen und Benachrichtigung bei persistenten Fehlern.
* **Retention Policy:** Automatisches Löschen alter zugestellter Mails nach 30 Tagen schont den Speicherplatz.

---

## Projektstruktur

```text
mailfetcher/
├── config/
│   └── config.yaml.example   # Vorlage für die Konfiguration
├── src/
│   └── fetcher.py            # Hauptprogramm (Python)
├── systemd/
│   ├── mailfetcher.service   # Systemd Dienst-Definition
│   └── mailfetcher.timer     # Systemd Timer (alle 5 Minuten)
├── install.sh                # Automatisches Installationsskript
├── requirements.txt          # Python-Abhängigkeiten
└── README.md                 # Dokumentation

```

Installation
Das mitgelieferte Installationsskript richtet die Ordnerstruktur unter /opt/mailfetcher ein, erstellt eine virtuelle Python-Umgebung (venv), installiert Abhängigkeiten und richtet die Systemd-Dienste ein.

Führe als root im geklonten Repository folgenden Befehl aus:

Bash
chmod +x install.sh
./install.sh
Konfiguration
Nach der Installation liegt unter /opt/mailfetcher/config.yaml deine Konfigurationsdatei. Bearbeite diese mit einem Texteditor (z. B. nano):

Bash
nano /opt/mailfetcher/config.yaml
Beispielhafte config.yaml:
YAML
# POP3-Zugangsdaten (E-Mail-Postfach abholen)
pop3:
  server: pop3.strato.de
  port: 995
  username: info@cooperlan.de
  password: "DEIN_PASSWORT"
  timeout: 30

# SMTP-Zugangsdaten (Interner Mailserver / Exchange)
smtp:
  server: ex01.ad.cooperlan.de
  port: 25
  default_sender: mailfetcher@cooperlan.de
  timeout: 30
  use_tls: false

# Admin-E-Mail für Fehlermeldungen
admin:
  email: admin@cooperlan.de

# Verhalten & Limits
options:
  delete_after_download: true   # Mails nach Download vom POP3-Server löschen
  max_retries: 10               # Maximale Zustellversuche vor Abgabe nach queue/failed

# Systempfade
paths:
  base: /opt/mailfetcher

# SMTP-Zugangsdaten (Interner Mailserver / Exchange)
smtp:
  server: ex01.ad.cooperlan.de
  port: 25
  default_sender: mailfetcher@cooperlan.de
  timeout: 30
  use_tls: false

# Admin-E-Mail für Fehlermeldungen
admin:
  email: admin@cooperlan.de

# Verhalten & Limits
options:
  delete_after_download: true   # Mails nach Download vom POP3-Server löschen
  max_retries: 10               # Maximale Zustellversuche vor Abgabe nach queue/failed

# Systempfade
paths:
  base: /opt/mailfetcher
Dienst starten & steuern
Der Mailfetcher wird über einen Systemd Timer gesteuert, der alle 5 Minuten das Python-Skript aufruft.

1. Timer aktivieren und starten:
Bash
systemctl enable --now mailfetcher.timer
2. Status prüfen:
Timer-Status: systemctl status mailfetcher.timer

Nächste Ausführung anzeigen: systemctl list-timers | grep mailfetcher

Service-Status (letzter Durchlauf): systemctl status mailfetcher.service

3. Manuelle Ausführung (Testlauf):
Du kannst den Mailfetcher jederzeit manuell anstoßen, ohne auf den Timer zu warten:

Bash
systemctl start mailfetcher.service
Oder direkt über die Python-Umgebung ausführen:

Bash
/opt/mailfetcher/venv/bin/python /opt/mailfetcher/src/fetcher.py
Monitoring & Fehlerbehebung
Logs einsehen
Der Mailfetcher schreibt ausführliche Informationen in seine Log-Datei:

Bash
tail -f /opt/mailfetcher/logs/fetcher.log
Alternativ kannst du die Systemd-Logs nutzen:

Bash
journalctl -u mailfetcher.service -n 50 --no-pager
Was tun, wenn E-Mails in queue/failed landen?
Prüfe die Log-Datei (fetcher.log), um den Grund für das Scheitern zu ermitteln (z. B. fehlerhafte Empfängeradresse oder Exchange nicht erreichbar).

Korrigiere das zugrunde liegende Problem.

Verschiebe die .eml-Datei manuell zurück in den pending-Ordner, um eine erneute Zustellung zu erzwingen:

Bash
mv /opt/mailfetcher/queue/failed/*.eml /opt/mailfetcher/queue/pending/
Lizenz
Dieses Projekt steht unter der GNU General Public License v3.0 (GPLv3).

Copyright (c) 2026 Tim Böttcher [cptmittelstahl42]

Details siehe Datei LICENSE.
