"""UAE e-invoicing: Peppol PINT-AE (UBL 2.1) invoice. The invoice is not sent to the tax authority directly:
it goes through an Accredited Service Provider (ASP) that forwards it on the Peppol network and reports to the FTA.
Built from the public PINT AE billing profile; the ASP validates the document, so run its test environment first."""
from lxml import etree

from .common import money
from .zatca import NS, _t, q

CUSTOMIZATION = "urn:peppol:pint:billing-1@ae-1"
PROFILE = "urn:peppol:bis:billing"
TYPE_CODE = {"invoice": "380", "credit": "381", "debit": "383"}


def _party(parent, wrapper, p, endpoint_scheme):
	party = _t(_t(parent, wrapper), "cac:Party")
	if p.get("endpoint"):
		_t(party, "cbc:EndpointID", p["endpoint"], schemeID=endpoint_scheme)
	if p.get("tax_id"):
		_t(_t(party, "cac:PartyIdentification"), "cbc:ID", p["tax_id"], schemeID=endpoint_scheme)
	a = p.get("address") or {}
	addr = _t(party, "cac:PostalAddress")
	_t(addr, "cbc:StreetName", a.get("street") or "-")
	_t(addr, "cbc:CityName", a.get("city") or "-")
	_t(addr, "cbc:CountrySubentity", a.get("governate") or "-")
	_t(_t(addr, "cac:Country"), "cbc:IdentificationCode", a.get("country") or "AE")
	if p.get("tax_id"):
		ts = _t(party, "cac:PartyTaxScheme")
		_t(ts, "cbc:CompanyID", p["tax_id"])
		_t(_t(ts, "cac:TaxScheme"), "cbc:ID", "VAT")
	le = _t(party, "cac:PartyLegalEntity")
	_t(le, "cbc:RegistrationName", p.get("name") or "-")
	if p.get("reg_no"):
		_t(le, "cbc:CompanyID", p["reg_no"], schemeID=p.get("reg_scheme") or "TL")


def build_xml(inv, cfg):
	"""cfg: endpoint_scheme (default 0235 = UAE TIN), type_flags (InvoiceTypeCode@name), due_days, unit default."""
	root = etree.Element(q("inv:Invoice"), nsmap={None: NS["inv"], "cac": NS["cac"], "cbc": NS["cbc"]})
	_t(root, "cbc:CustomizationID", CUSTOMIZATION)
	_t(root, "cbc:ProfileID", PROFILE)
	_t(root, "cbc:ID", inv["id"])
	_t(root, "cbc:IssueDate", inv["issue_dt"].strftime("%Y-%m-%d"))
	if inv.get("due_date"):
		_t(root, "cbc:DueDate", inv["due_date"])
	_t(root, "cbc:InvoiceTypeCode", TYPE_CODE.get(inv["kind"], "380"), name=cfg.get("type_flags") or "00000000")
	if inv.get("notes"):
		_t(root, "cbc:Note", inv["notes"])
	cur = inv["currency"]
	_t(root, "cbc:DocumentCurrencyCode", cur)
	if inv.get("reference"):
		_t(_t(root, "cac:BillingReference"), "cac:InvoiceDocumentReference")
		root[-1][0].append(etree.Element(q("cbc:ID")))
		root[-1][0][0].text = inv["reference"]
	scheme = cfg.get("endpoint_scheme") or "0235"
	_party(root, "cac:AccountingSupplierParty", inv["seller"], scheme)
	_party(root, "cac:AccountingCustomerParty", inv["buyer"], scheme)
	_t(_t(root, "cac:PaymentMeans"), "cbc:PaymentMeansCode", (inv.get("payment") or {}).get("means") or "30")
	t = inv["totals"]
	tx = _t(root, "cac:TaxTotal")
	_t(tx, "cbc:TaxAmount", money(t["tax"]), currencyID=cur)
	groups = {}
	for ln in inv["lines"]:
		g = groups.setdefault(ln["tax_rate"], [0.0, 0.0])
		g[0] += ln["net"]
		g[1] += ln["tax"]
	for rate, (net, tax) in groups.items():
		sub = _t(tx, "cac:TaxSubtotal")
		_t(sub, "cbc:TaxableAmount", money(net), currencyID=cur)
		_t(sub, "cbc:TaxAmount", money(tax), currencyID=cur)
		cat = _t(sub, "cac:TaxCategory")
		_t(cat, "cbc:ID", "S" if rate else "Z")
		_t(cat, "cbc:Percent", money(rate))
		_t(_t(cat, "cac:TaxScheme"), "cbc:ID", "VAT")
	lm = _t(root, "cac:LegalMonetaryTotal")
	_t(lm, "cbc:LineExtensionAmount", money(t["net"]), currencyID=cur)
	_t(lm, "cbc:TaxExclusiveAmount", money(t["net"]), currencyID=cur)
	_t(lm, "cbc:TaxInclusiveAmount", money(t["grand"]), currencyID=cur)
	_t(lm, "cbc:PayableAmount", money(t["grand"]), currencyID=cur)
	for ln in inv["lines"]:
		il = _t(root, "cac:InvoiceLine")
		_t(il, "cbc:ID", ln["idx"])
		_t(il, "cbc:InvoicedQuantity", f"{ln['qty']:.4f}", unitCode=ln["unit"] or "C62")
		_t(il, "cbc:LineExtensionAmount", money(ln["net"]), currencyID=cur)
		item = _t(il, "cac:Item")
		_t(item, "cbc:Name", ln["description"] or ln["code"] or "-")
		ct = _t(item, "cac:ClassifiedTaxCategory")
		_t(ct, "cbc:ID", "S" if ln["tax_rate"] else "Z")
		_t(ct, "cbc:Percent", money(ln["tax_rate"]))
		_t(_t(ct, "cac:TaxScheme"), "cbc:ID", "VAT")
		_t(_t(il, "cac:Price"), "cbc:PriceAmount", f"{(ln['net'] / ln['qty']) if ln['qty'] else 0:.4f}", currencyID=cur)
	return root


def to_string(root):
	return etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode()
