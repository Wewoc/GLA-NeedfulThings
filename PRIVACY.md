# Privacy Policy – "OpenClaw Mail" (personal Gmail tooling)

*Datenschutzerklärung / Privacy policy. English first, German below.*

## English

**What this is.** "OpenClaw Mail" is a private, single-user tool that the repository owner runs on their own computer. It lets a locally run AI assistant list, read, label, archive and trash messages in the owner's **own** Gmail account. It is not a public service and is not offered to other users.

**What data is accessed.** Using the Google OAuth scope `https://www.googleapis.com/auth/gmail.modify`, the tool reads message metadata (sender, subject, date, snippet, labels), message text on request, and changes labels / moves messages to the trash on the owner's request. The tool does not implement sending email.

**Where data goes.** All processing happens locally on the owner's computer (a local Docker container and a locally hosted language model via Ollama). The owner's mail data is **not** sent to the developer, to any server operated by the developer, or to any third party. No analytics, tracking, advertising or profiling. Data is not sold or shared. No human other than the account owner reads the data.

**Storage.** OAuth credentials (client secret, refresh token) are stored only on the owner's computer, in the local secret store of the software. Mail content is not stored by the tool beyond what the local assistant keeps in its own local chat history on that computer.

**Choices made by the owner.** If the owner configures a cloud-hosted language model instead of a local one, message content processed by the assistant would be sent to that provider at the owner's own discretion and responsibility.

**Google API Services User Data Policy.** The use of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

**Revoking access.** Access can be revoked at any time at <https://myaccount.google.com/permissions>. Locally stored credentials can be deleted by removing the secrets from the software's secret store.

**Contact.** Please open an issue in this GitHub repository.

*Last updated: 2026-10-13*

## Deutsch

**Worum es geht.** "OpenClaw Mail" ist ein privates Ein-Personen-Werkzeug, das der Repository-Inhaber auf dem eigenen Rechner betreibt. Ein lokal laufender KI-Assistent kann damit Nachrichten im **eigenen** Gmail-Konto des Inhabers auflisten, lesen, mit Labels versehen, archivieren und in den Papierkorb verschieben. Es ist kein öffentlicher Dienst und wird keinen anderen Nutzern angeboten.

**Welche Daten.** Über den Google-OAuth-Bereich `https://www.googleapis.com/auth/gmail.modify` liest das Werkzeug Nachrichten-Metadaten (Absender, Betreff, Datum, Vorschautext, Labels) und auf Anforderung den Nachrichtentext und ändert Labels bzw. verschiebt Nachrichten in den Papierkorb. Ein Versand von E-Mails ist im Werkzeug nicht umgesetzt.

**Wohin die Daten gehen.** Die gesamte Verarbeitung findet lokal auf dem Rechner des Inhabers statt (lokaler Docker-Container und lokal betriebenes Sprachmodell über Ollama). Die Maildaten werden **nicht** an den Entwickler, an Server des Entwicklers oder an Dritte übermittelt. Keine Analyse, kein Tracking, keine Werbung, kein Profiling. Keine Weitergabe oder Verkauf. Außer dem Kontoinhaber liest niemand die Daten.

**Speicherung.** Die OAuth-Zugangsdaten (Client-Secret, Refresh-Token) liegen nur auf dem Rechner des Inhabers im lokalen Secret-Store der Software. Mail-Inhalte werden vom Werkzeug nicht gespeichert, über den lokalen Chatverlauf des Assistenten auf demselben Rechner hinaus.

**Entscheidung des Inhabers.** Konfiguriert der Inhaber statt eines lokalen Modells ein Cloud-Sprachmodell, würden vom Assistenten verarbeitete Nachrichteninhalte auf eigene Entscheidung und Verantwortung des Inhabers an diesen Anbieter gesendet.

**Google API Services User Data Policy.** Die Verwendung von Informationen aus Google-APIs erfolgt gemäß der [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), einschließlich der Anforderungen zur eingeschränkten Nutzung (Limited Use).

**Zugriff widerrufen.** Der Zugriff kann jederzeit unter <https://myaccount.google.com/permissions> widerrufen werden. Lokal gespeicherte Zugangsdaten lassen sich löschen, indem die Secrets aus dem Secret-Store der Software entfernt werden.

**Kontakt.** Bitte ein Issue in diesem GitHub-Repository eröffnen.

*Stand: 13.10.2026*
