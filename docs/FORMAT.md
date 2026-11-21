# Geräteprotokoll Blackout-Station · Formatbeschreibung v0.5

Stand 19.11.2026 · für Teilnehmende · alle Personen und Codes sind erfunden

## 1. Überblick

Jedes Team betreibt **eine Station** mit einer eigenen `station_id`, z. B. `ST-T1`. Die Station führt ein Protokoll. Jedes Ereignis ist eine Zeile JSON (JSON Lines, UTF-8, Zeilenende `\n`). Die Einträge sind fortlaufend nummeriert, über Hashes verkettet und mit dem Schlüssel der Station signiert.

```
seq 1 genesis ──hash──▶ seq 2 checkin ──hash──▶ seq 3 walkin ──▶ … ──▶ seq n handover
```

Station, Papier und Handy der Helfenden schreiben alle in **dasselbe** Protokoll. Mit dem Server spricht nur die Station.

## 2. Aufbau eines Eintrags

```json
{"v":1,"station_id":"ST-T1","seq":2,"type":"checkin",
 "recorded_at":"2026-11-21T09:02:17+01:00",
 "payload":{"code":"K7M-4PX","source":{"kind":"station"}},
 "prev_hash":"…","hash":"…","sig":"…"}
```

| Feld | Typ | Bedeutung |
|---|---|---|
| `v` | Zahl | Formatversion, immer `1` |
| `station_id` | Text | von der Orga vergeben: `ST-T1` bis `ST-T4` |
| `seq` | Zahl | 1, 2, 3, … ohne Lücke |
| `type` | Text | `genesis`, `checkin`, `checkout`, `walkin`, `rejected`, `handover` |
| `recorded_at` | Text | Erfassungszeit laut Gerät (Abschnitt 4) |
| `payload` | Objekt | abhängig vom Typ (Abschnitt 3) |
| `prev_hash` | Text | `hash` des vorigen Eintrags; bei `seq` 1: 64 Nullen |
| `hash` | Text | SHA-256 über den Eintrag, 64 Zeichen hex, klein |
| `sig` | Text | Ed25519-Signatur, Base64 |

**Erlaubte Werte:** nur Text, ganze Zahlen, `true`/`false`, Objekte und Listen. Keine Kommazahlen, kein `null`.

## 3. Ereignistypen

**`genesis`** – immer `seq` 1, genau einmal
```json
{"station_pubkey":"<Base64, 32 Byte>","team_id":"T1","app_version":"0.3.0"}
```
`station_pubkey` muss der bei der Orga registrierte Schlüssel sein.

**`checkin` / `checkout`** – vorab Eingetragene per Code, Spontane per `walkin_id`
```json
{"code":"K7M-4PX","source":{"kind":"station"}}
{"walkin_id":"W-T1-0003","source":{"kind":"station"}}
```

**`walkin`** – spontan Erscheinende erfassen, gilt zugleich als Check-in
```json
{"walkin_id":"W-T1-0003","name":"Lena Beispiel","role_claimed":"gelb",
 "skill":"Pflegefachkraft","consent":true,"consent_version":"1.0",
 "source":{"kind":"station"}}
```
- `walkin_id` vergibt die Station: `W-<Team>-<4 Ziffern>`, z. B. `W-T1-0003`
- `role_claimed`: `gruen` (Freiwillige), `gelb` (Fachkraft) oder `rot` (Spezialist), so wie die Person es angibt. Die Station prüft keine Qualifikation.
- Ohne `consent: true` wird kein `walkin` geschrieben.

**`rejected`** – ein Versuch, den die Station abgewiesen hat
```json
{"attempt":"checkin","reason":"unknown_code","code":"X3K-9PZ","source":{"kind":"station"}}
```
- `attempt`: was versucht wurde, `checkin`, `checkout` oder `walkin`
- `reason`: warum die Station abgelehnt hat

| `reason` | Bedeutung |
|---|---|
| `unknown_code` | Code steht nicht in der Liste |
| `already_checked_in` | Person ist an dieser Station schon eingecheckt |
| `not_checked_in` | Check-out, ohne vorher eingecheckt zu sein |
| `no_consent` | spontan Erscheinende ohne Einwilligung |
| `remote_suspected` | Handy-Check-in, bei dem die Person vermutlich nicht vor Ort ist |
| `other` | anderer Grund, bitte in `note` (Text) beschreiben |

- Dazu, soweit vorhanden, `code` oder `walkin_id` und `source` wie bei den anderen Typen.
- Bei `no_consent` keinen Namen speichern.
- Abgewiesene Versuche gehören ins Protokoll. Nur so kann die Bewertung erkennen, dass eure Station einen Angriff abgewehrt hat.

**Codes** haben das Muster `XXX-XXX` aus `A–Z` ohne I und O sowie `2–9`. Die Liste gültiger Codes bekommt ihr am Freitagabend als `codeliste.json` (Felder `code`, `role`, `skill`) zum Einbauen in die App.

### Quellen: Station, Papier, Handy

Jeder `checkin`, `checkout`, `walkin` und `rejected` gibt in `source.kind` an, woher er stammt:

| `kind` | Bedeutung | Zusatzfelder |
|---|---|---|
| `station` | direkt am Gerät der Station erfasst | – |
| `paper` | Zeile vom Papierbogen, von einem Menschen bestätigt | `sheet`, `line`, `confirmed: true`; im Payload zusätzlich `occurred_at` |
| `phone` | Helfende haben sich mit dem eigenen Handy gemeldet, die Station hat es geprüft | `proof`: Objekt, Inhalt legt ihr selbst fest |

```json
"source":{"kind":"paper","sheet":"P-T1-02","line":7,"confirmed":true},
"occurred_at":"2026-11-21T09:08:00+01:00"

"source":{"kind":"phone","proof":{"method":"…","challenge":"…"}}
```

- Unbestätigte Papierzeilen kommen nicht ins Protokoll. Fotos und Unterschriften werden nicht gespeichert.
- **Handy (Zusatzaufgabe):** Das Handy der Helfenden überträgt nichts an den Server. Es weist sich an der Station aus, und die Station schreibt den Eintrag. Ein Check-in aus der Ferne, etwa mit einem weitergeschickten Screenshot, darf nicht funktionieren. Wie ihr das erreicht und wo die Grenzen liegen, gehört in euren Pitch.

**`handover`** – letzter Eintrag vor jeder Übertragung
```json
{"last_seq":42,"count":42}
```
`last_seq` und `count` sind beide die `seq` des handover selbst (er zählt sich mit). Schreibt den handover unmittelbar vor dem Senden. Schließt die Kette ab. Fehlt er, kann der Server nicht ausschließen, dass am Ende Einträge fehlen. Außerdem misst der Server damit eure Uhrabweichung. Nach einer Übertragung darf die Station weiterschreiben; vor der nächsten Übertragung kommt ein neuer `handover`.

## 4. Zeitangaben

Alle Zeiten in ISO 8601 mit Zeitzone, z. B. `2026-11-21T09:02:17+01:00`.

| Feld | Wer setzt sie | Genauigkeit |
|---|---|---|
| `recorded_at` | das Gerät, automatisch beim Schreiben bzw. bei der Bestätigung einer Papierzeile | sekundengenau |
| `occurred_at` | ein Mensch, von Hand auf dem Papierbogen | minutengenau, Sekunden immer `:00` |

**Falsch gehende Uhr:** Beim `handover` vergleicht der Server dessen `recorded_at` mit seiner Empfangszeit. Ab 2 Minuten Abweichung gibt es `W_UHR`, und alle Zeiten dieser Station werden um die Abweichung korrigiert. Abgelehnt wird nichts.

**Plausibilität:** Nach der Uhrkorrektur müssen alle Einträge der Blackout-Runde innerhalb der Rundenzeit liegen. Die genaue Zeit erfahrt ihr am Freitagabend.

## 5. Hash und Signatur

1. Eintrag ohne `hash` und `sig` nehmen.
2. **Kanonisch** serialisieren: Schlüssel sortiert (auch verschachtelt), keine Leerzeichen, UTF-8, Umlaute nicht escapen.
3. `hash` = SHA-256 davon, als hex.
4. `sig` = Ed25519-Signatur über die **32 Rohbytes** des Hashes, als Base64.

```python
import json, hashlib, base64
def canonical(d): return json.dumps(d, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")
body = {k: v for k, v in eintrag.items() if k not in ("hash", "sig")}
eintrag["hash"] = hashlib.sha256(canonical(body)).hexdigest()
eintrag["sig"]  = base64.b64encode(private_key.sign(bytes.fromhex(eintrag["hash"]))).decode()
```

Die Zeile in der Datei muss nicht kanonisch sein. Geprüft wird immer die kanonische Form.

## 6. Schlüssel und Station

- Jede Station erzeugt ihr Ed25519-Schlüsselpaar **selbst**. Der private Schlüssel verlässt das Gerät nie.
- Den öffentlichen Schlüssel (32 Byte, Base64) registriert ihr bis **Freitag, 20.11., 22:00** über `POST /v1/station/key`. Die Antwort enthält eure `station_id`, die ihr ab `genesis` in jeden Eintrag schreibt:
  ```
  curl -X POST https://<server>/v1/station/key \
       -H "Authorization: Bearer <Team-Token>" -H "Content-Type: application/json" \
       -d '{"pubkey_b64":"<euer öffentlicher Schlüssel>"}'
  → {"station_id":"ST-T1","pubkey_b64":"…","ersetzt":false}
  ```
- Solange eure Station noch keine Einträge übertragen hat, dürft ihr den Schlüssel bis 22:00 erneut registrieren (z. B. nach einem Neustart der App). Danach gilt er fest.
- Nach 22:00 oder bei Problemen registriert die Orga den Schlüssel für euch: zeigt ihr dafür euren öffentlichen Schlüssel.
- **Ersatzgerät:** Fällt die Station am Samstag aus, meldet euch bei der Orga. Das Ersatzgerät bekommt eine neue `station_id` (z. B. `ST-T1B`), einen neuen Schlüssel und beginnt eine neue Kette. Was die alte Station schon übertragen hat, zählt weiter.

## 7. API

Basis-Adresse und Team-Token stehen in eurer Zugangsmail. Jede Anfrage braucht:
```
Authorization: Bearer <Team-Token>
```
Der Token bestimmt euer Team. Ihr seht und ändert nur eure eigenen Daten. Einen anderen Zugang zum Server gibt es nicht.

| Methode und Pfad | Zweck |
|---|---|
| `GET /v1/health` | läuft der Server? Ohne Token. Liefert auch `server_time` |
| `POST /v1/station/key` | öffentlichen Schlüssel registrieren, Body `{"pubkey_b64":"…"}`, bis Freitag 22:00. Antwort enthält eure `station_id` |
| `POST /v1/check` | Protokoll **nur prüfen**, nichts wird gespeichert. Zum Testen, so oft ihr wollt. Vor der Registrierung wird gegen den Schlüssel aus `genesis` geprüft (`I_OHNE_SCHLUESSEL`) |
| `POST /v1/upload` | Protokoll übertragen, zählt für die Bewertung |
| `GET /v1/status` | `accepted_up_to`, Anzahl Einträge, Zeit der letzten Übertragung |
| `GET /v1/findings` | Befunde der letzten Prüfung |
| `GET /v1/events?from_seq=1&limit=500` | eure Einträge, wie der Server sie gespeichert hat, mit korrigierter Zeit. Weiterblättern mit `next_from_seq` |

`/v1/check` und `/v1/upload` erwarten `Content-Type: application/x-ndjson` und die Zeilen des Protokolls. Antwort:
```json
{"station_id":"ST-T1","stored":true,"accepted_up_to":42,"new":12,"duplicates":30,
 "conflicts":0,"chain_ok":true,"lines":42,"clock_offset_s":-14,"clock_correction_s":0,
 "findings":[{"seq":7,"code":"W_LOGIK","level":"warnung","detail":"…"}]}
```
`clock_offset_s` ist die gemessene Abweichung eurer Uhr beim `handover` (Gerät minus Server), `clock_correction_s` die tatsächlich abgezogene Korrektur (0, solange ihr innerhalb von 2 Minuten liegt). Fehlermeldungen kommen als `{"error":"…"}`.

Optionaler Header `X-Station-Id`: nur nötig, wenn ihr nach einem Ersatzgerät gezielt eine ältere Station abfragen wollt. Ohne ihn gilt eure aktive Station.

- Ihr dürft immer das ganze Protokoll oder alles ab `accepted_up_to + 1` schicken. Bekannte Einträge mit gleichem Hash werden still übersprungen. So kommt nichts doppelt an.
- Schlägt die Verbindung fehl, einfach wiederholen.
- Eine bekannte `seq` mit **anderem** Inhalt wird nie überschrieben, sondern als Konflikt gemeldet.
- Statuscodes:

| Code | Bedeutung |
|---|---|
| `200` / `201` | verarbeitet (Befunde stehen in `findings`) / Station neu angelegt |
| `400` | Body nicht lesbar, leer, kein UTF-8 oder ungültiger Schlüssel |
| `401` | Token fehlt, ist ungültig oder gesperrt |
| `403` | Anmeldeschluss vorbei oder Station gehört nicht zu euch |
| `409` | Konflikt (gleiche `seq`, anderer Inhalt) oder Schlüssel schon vergeben bzw. Station hat schon Einträge |
| `412` | Upload, bevor ein Schlüssel registriert ist |
| `413` | Body größer als 5 MB |
| `423` | Uploads gesperrt (ab Beginn der Prüfung nach der Blackout-Runde) |
| `429` | zu viele Anfragen (mehr als 120 pro Minute), kurz warten |

## 8. Was der Server prüft

| Code | Stufe | Bedeutung |
|---|---|---|
| `E_SCHEMA` | Fehler | Pflichtfeld fehlt, Typ, Quelle oder `reason` unbekannt, Zeit nicht lesbar, `occurred_at` mit Sekunden |
| `E_GENESIS` | Fehler | `seq` 1 ist kein `genesis` oder falscher Schlüssel |
| `E_HASH` | Fehler | Inhalt passt nicht zum Hash |
| `E_SIGNATUR` | Fehler | Signatur passt nicht zum registrierten Schlüssel |
| `E_KETTE` | Fehler | `prev_hash` passt nicht zum Vorgänger |
| `E_LUECKE` | Fehler | Nummer fehlt |
| `E_KONFLIKT` | Fehler | gleiche Nummer, anderer Inhalt |
| `W_ENDE` | Warnung | letzter Eintrag ist kein `handover` |
| `W_UHR` | Warnung | Geräteuhr weicht mehr als 2 Minuten ab |
| `W_LOGIK` | Warnung | Widerspruch in einer gültigen Kette: Code steht nicht in der Codeliste, Check-in obwohl schon eingecheckt, Check-out ohne Check-in, `walkin_id` doppelt vergeben oder nie erfasst, derselbe Code zur selben Zeit an einer anderen Station |
| `I_DUPLIKAT` | Info | Eintrag schon bekannt, ignoriert |
| `I_OHNE_SCHLUESSEL` | Info | nur `/v1/check`: noch kein Schlüssel registriert, geprüft gegen `genesis` |

**Was übernommen wird:** Nur Einträge, die die gültige Kette lückenlos fortsetzen. Ab dem ersten Fehler (`E_*`) wird nichts mehr übernommen, aber alles Weitere geprüft und gemeldet. Korrigiert die Ursache und schickt ab `accepted_up_to + 1` erneut. Eine Zeile, die kein JSON ist, wird gemeldet, unterbricht die Kette aber nicht.

## 9. Testen

Im Ordner `testfaelle/` findet ihr:

- `T1_gueltig.jsonl`: ein vollständiges, gültiges Protokoll mit 11 Einträgen aus allen drei Quellen, inklusive eines abgewiesenen Versuchs
- `testschluessel.json`: der Schlüssel, mit dem T1 signiert ist. Er ist öffentlich und nur für diesen Test gedacht. Der Server lehnt ihn für jede echte Station ab.
- `T1_erwartet.json`: die 11 erwarteten Hashes

**Eure App ist formatkonform**, wenn sie mit dem Testschlüssel aus denselben Inhalten Zeichen für Zeichen dieselben Hashes erzeugt. Danach prüft ihr euer eigenes Protokoll mit `POST /v1/check`.

## 10. So wird am Samstag gemessen

Es gibt kein Drehbuch. Wer eure Station besucht und wann, ist offen, wie im Ernstfall. Es gelten zwei Regeln für die Personen mit Rollenkarten (Mitglieder anderer Teams oder die Orga):

- **Pflichtbesuch:** Jede Rollenkarte meldet sich an jeder fremden Station einmal an und wieder ab. Zeitpunkt und Reihenfolge sind frei.
- **Angriffe:** Jede Station erlebt genau einmal jeden der fünf Angriffe aus der Tabelle unten. Wann und von wem, sagen wir nicht.

Spontan Erscheinende kann es jederzeit und beliebig viele geben.

### Die fünf Angriffe an der Station

Eure App soll jeden davon von selbst erkennen, abweisen und als `rejected` protokollieren:

| Angriff | Was passiert | Erwarteter Eintrag |
|---|---|---|
| Erfundener Code | Jemand nennt einen Code, der in keiner Liste steht | `rejected`, `attempt: checkin`, `reason: unknown_code`, `code` = der genannte Code |
| Doppelter Check-in | Jemand ist an eurer Station eingecheckt und versucht es mit demselben Code noch einmal | `rejected`, `attempt: checkin`, `reason: already_checked_in`, `code` |
| Abmelden ohne Anmelden | Jemand will sich mit seinem Code abmelden, ohne an eurer Station eingecheckt zu sein | `rejected`, `attempt: checkout`, `reason: not_checked_in`, `code` |
| Ohne Einwilligung | Eine spontan erscheinende Person lehnt die Einwilligung ab | `rejected`, `attempt: walkin`, `reason: no_consent`, **ohne Namen** |
| Handy aus der Ferne | Jemand zeigt ein Foto oder eine Weiterleitung des Handy-Check-ins einer anderen Person | `rejected`, `attempt: checkin`, `reason: remote_suspected` |

- Der Angriff „Handy aus der Ferne“ zählt nur, wenn eure Station Handy-Check-in anbietet.
- Gewertet wird, ob der passende `rejected`-Eintrag im übertragenen Protokoll steht; Reihenfolge und Uhrzeit spielen keine Rolle. Beim erfundenen Code muss es genau der genannte Code sein. Die Anzahl abgewiesener Versuche je Station wird der Jury gezeigt.
- Rutscht ein Angriff als gültiger Eintrag durch (z. B. ein Check-in mit erfundenem Code), zählt er als nicht erkannt.

### Prüfung nach der Runde

Nach der Blackout-Runde übertragt ihr euer Protokoll, dann werden die Uploads gesperrt. Wir manipulieren eine **Kopie** eurer übertragenen Daten: Einträge löschen, Inhalte ändern (mit und ohne neu berechneten Hash), Einträge erfinden, doppelt einspielen und das Ende abschneiden. Der Prüfserver muss jeden Eingriff erkennen. Das gelingt nur, wenn euer Protokoll korrekt verkettet, signiert und mit `handover` abgeschlossen ist. Eure Geräte bleiben dabei die ganze Zeit bei euch.

### Bewertung

| Kriterium | Anteil | Wie gemessen |
|---|---|---|
| Vollständig und richtig | 30 % | Anteil der Pflichtbesuche (An- und Abmeldung), die korrekt im Protokoll stehen, und Anteil fehlerfreier Einträge |
| Manipulation erkannt: Protokoll | 10 % | Anteil der Eingriffe an der Kopie, die der Prüfserver erkennt |
| Manipulation erkannt: Station | 15 % | Anteil der fünf Angriffe, die eure Station abgewiesen und passend als `rejected` protokolliert hat |
| Schnell und verständlich bedienbar | 20 % | Jury, Check-in-Dauer mit Stoppuhr |
| Ehrliche Grenze | 15 % | Jury |
| Pitch | 10 % | Jury |

Die genauen Uhrzeiten von Blackout-Runde, Prüfung und Ergebnis erfahrt ihr am Freitagabend.
