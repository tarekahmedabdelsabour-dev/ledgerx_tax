# LedgerX E-Invoicing

Sends Sales Invoices to a tax system and keeps the answer on the invoice. One framework, one adapter per system, and a configurable connector for any other.

| System | What it does |
|---|---|
| Egypt ETA | Builds invoice v1.0, canonical serialization, signing through your signing service, submit, status check, cancel |
| Saudi ZATCA | UBL 2.1 invoice, hash chain, ECDSA signature, QR (TLV), certificate request, compliance and production certificates, reporting and clearance |
| UAE | PINT-AE invoice sent to your accredited service provider |
| Custom API | URL, headers and a Jinja body template for any other country or provider |

Credit notes (returns) and debit notes are sent too. Everything runs in the background with automatic retries every 10 minutes; each attempt is kept in **E-Invoice Submission** with the request and the answer.

## Status: read this first
The calculation parts (documents, hashes, signatures, QR, request building, answer reading) are unit tested here with simulated tax systems. **Nothing has been run against a real authority**: no test accounts were available. Treat each country as "built to the published specification, needs your first test run":

- Egypt: you need a registered ERP, a client id and secret, a digital seal (eSeal) and a signing service (see `docs/INSTALL.md`).
- Saudi: run the four onboarding steps on the simulation portal and make the compliance checks pass before any real invoice.
- UAE: the system works through an accredited service provider; its API differs per provider, so the request is configurable.

See `docs/INSTALL.md`.
