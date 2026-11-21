# Install

```bash
cd ~/frappe-bench-v16
git clone <repo-url> apps/ledgerx_tax
printf '\nledgerx_tax\n' >> sites/apps.txt
./env/bin/pip install -e apps/ledgerx_tax
./env/bin/pip install lxml cryptography requests jinja2
ln -sfn ~/frappe-bench-v16/apps/ledgerx_tax/ledgerx_tax/public sites/assets/ledgerx_tax
bench --site mysite.localhost install-app ledgerx_tax
bench --site mysite.localhost migrate
bench --site mysite.localhost clear-cache
```
Restart, then Ctrl+Shift+R.

## For every country
1. Open **E-Invoice Connection**, create one per company, choose the system and the environment (Test first).
2. Fill the seller block (tax number, address). It must match what the authority has on file.
3. On each **Item** set the e-invoice code (and type), on each **UOM** the unit code, on **Customer** the tax number and buyer type.
4. Use **Preview E-Invoice** on a submitted invoice to see exactly what would be sent. Then **Send to the Tax Authority**.
5. Turn on *Send Automatically* when the test works.

## Egypt
Client id and secret come from the authority's taxpayer portal (ERP registration). Every document needs a CAdES-BES signature made with your eSeal certificate, which normally lives on a USB token or an HSM, so the app asks a **signing service** you run next to it:

`POST <Signing Service Address>`  body `{"canonical": "<string>", "sha256": "<hex>"}`, header `Authorization: Bearer <key>`
answer `{"signature": "<base64 CAdES-BES over the SHA-256 of the canonical string>"}`

The authority's own signing guide and sample code describe how to produce that signature. Without a signing service choose *None (test only)*: the authority will reject the invoices.

## Saudi Arabia
On the connection press, in order: **1. Generate Certificate Request**, enter the one-time code (OTP) from the FATOORA portal, **2. Get Compliance Certificate**, **3. Run Compliance Checks** (six sample invoices), **4. Get Production Certificate**. Do this on *Simulation* first. The private key stays on the site. The counter and hash chain are kept on the connection; only accepted invoices advance it.
A sent invoice cannot be cancelled: issue a credit note.

## UAE
Choose an accredited service provider, put its API address and credentials on the connection, then set the answer fields (success field, reference field). If the provider wants a special body use the body template (`xml` and `xml_b64` are available).

## Any other system
Choose *Custom API*, set the address, sign-in method and a Jinja body template, e.g. `{{ inv | tojson }}`.
