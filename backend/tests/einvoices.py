"""Made-up e-invoices for the tests: an XRechnung in UBL, one in CII, a ZUGFeRD PDF with its XML inside, and hostile XML
(entities, an external DTD, an entity bomb, a very deep tree). Nothing real: Elektro Brandt GmbH, Stadtwerke Lindenau,
example.com, and IBANs made here with right check digits for made-up bank codes."""

from __future__ import annotations

import io

from .files import make_pdf


def iban(country: str, bank: str, account: str) -> str:
    """An IBAN with right check digits for a made-up bank code and account."""
    body = bank + account
    moved = body + country + "00"
    digits = "".join(str(int(char, 36)) for char in moved)
    check = 98 - int(digits) % 97
    return f"{country}{check:02d}{body}"


SELLER_IBAN = iban("DE", "12030000", "0000202051")
OTHER_IBAN = iban("DE", "50010517", "5407324931")


def ubl(number: str = "RE-26-0912", *, seller: str = "Glanzwerk Reinigungsservice", xrechnung: bool = True,
        account: str = OTHER_IBAN) -> bytes:
    custom = ("urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0" if xrechnung
              else "urn:cen.eu:en16931:2017")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
 <cbc:CustomizationID>{custom}</cbc:CustomizationID>
 <cbc:ID>{number}</cbc:ID>
 <cbc:IssueDate>2026-09-30</cbc:IssueDate>
 <cbc:DueDate>2026-10-14</cbc:DueDate>
 <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
 <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
 <cbc:BuyerReference>04011000-12345-67</cbc:BuyerReference>
 <cac:AccountingSupplierParty><cac:Party>
  <cac:PartyName><cbc:Name>{seller}</cbc:Name></cac:PartyName>
  <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID></cac:PartyTaxScheme>
  <cac:PartyLegalEntity><cbc:RegistrationName>{seller}</cbc:RegistrationName></cac:PartyLegalEntity>
 </cac:Party></cac:AccountingSupplierParty>
 <cac:AccountingCustomerParty><cac:Party>
  <cac:PartyLegalEntity><cbc:RegistrationName>Ferienwohnung Lindenhof</cbc:RegistrationName></cac:PartyLegalEntity>
 </cac:Party></cac:AccountingCustomerParty>
 <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
  <cac:PayeeFinancialAccount><cbc:ID>{account}</cbc:ID></cac:PayeeFinancialAccount></cac:PaymentMeans>
 <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">53.20</cbc:TaxAmount></cac:TaxTotal>
 <cac:LegalMonetaryTotal>
  <cbc:LineExtensionAmount currencyID="EUR">280.00</cbc:LineExtensionAmount>
  <cbc:TaxExclusiveAmount currencyID="EUR">280.00</cbc:TaxExclusiveAmount>
  <cbc:TaxInclusiveAmount currencyID="EUR">333.20</cbc:TaxInclusiveAmount>
  <cbc:PayableAmount currencyID="EUR">333.20</cbc:PayableAmount>
 </cac:LegalMonetaryTotal>
 <cac:InvoiceLine><cbc:ID>1</cbc:ID>
  <cbc:InvoicedQuantity unitCode="C62">4</cbc:InvoicedQuantity>
  <cbc:LineExtensionAmount currencyID="EUR">280.00</cbc:LineExtensionAmount>
  <cac:Item><cbc:Name>Endreinigung Ferienwohnung Lindenhof</cbc:Name></cac:Item>
  <cac:Price><cbc:PriceAmount currencyID="EUR">70.00</cbc:PriceAmount></cac:Price>
 </cac:InvoiceLine>
</Invoice>
""".encode()


def cii(number: str = "2026-0473", *, seller: str = "Elektro Brandt GmbH", guideline: str = "urn:cen.eu:en16931:2017",
        account: str = SELLER_IBAN, gross: str = "224.91") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
 xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
 <rsm:ExchangedDocumentContext>
  <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>{guideline}</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
 </rsm:ExchangedDocumentContext>
 <rsm:ExchangedDocument>
  <ram:ID>{number}</ram:ID><ram:TypeCode>380</ram:TypeCode>
  <ram:IssueDateTime><udt:DateTimeString format="102">20261006</udt:DateTimeString></ram:IssueDateTime>
 </rsm:ExchangedDocument>
 <rsm:SupplyChainTradeTransaction>
  <ram:IncludedSupplyChainTradeLineItem>
   <ram:SpecifiedTradeProduct><ram:Name>Wartung Gasbrennwerttherme</ram:Name></ram:SpecifiedTradeProduct>
   <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>129.00</ram:ChargeAmount>
   </ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
   <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
   <ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation>
    <ram:LineTotalAmount>129.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
   </ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
  <ram:IncludedSupplyChainTradeLineItem>
   <ram:SpecifiedTradeProduct><ram:Name>Anfahrt</ram:Name></ram:SpecifiedTradeProduct>
   <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>35.00</ram:ChargeAmount>
   </ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
   <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
   <ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation>
    <ram:LineTotalAmount>35.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
   </ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
  <ram:ApplicableHeaderTradeAgreement>
   <ram:BuyerReference>LINDENHOF-12</ram:BuyerReference>
   <ram:SellerTradeParty><ram:Name>{seller}</ram:Name>
    <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE987654321</ram:ID></ram:SpecifiedTaxRegistration>
   </ram:SellerTradeParty>
   <ram:BuyerTradeParty><ram:Name>Ferienwohnung Lindenhof</ram:Name></ram:BuyerTradeParty>
  </ram:ApplicableHeaderTradeAgreement>
  <ram:ApplicableHeaderTradeSettlement>
   <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
   <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode>
    <ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{account}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>
   </ram:SpecifiedTradeSettlementPaymentMeans>
   <ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">20261020</udt:DateTimeString>
   </ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
   <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    <ram:LineTotalAmount>189.00</ram:LineTotalAmount>
    <ram:TaxBasisTotalAmount>189.00</ram:TaxBasisTotalAmount>
    <ram:TaxTotalAmount currencyID="EUR">35.91</ram:TaxTotalAmount>
    <ram:GrandTotalAmount>{gross}</ram:GrandTotalAmount>
    <ram:DuePayableAmount>{gross}</ram:DuePayableAmount>
   </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
  </ram:ApplicableHeaderTradeSettlement>
 </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
""".encode()


def zugferd_pdf(xml: bytes | None = None, name: str = "factur-x.xml", lines: tuple[str, ...] = ()) -> bytes:
    """A PDF whose page shows the invoice and that carries the XML as an attached file (as ZUGFeRD and Factur-X do)."""
    import pikepdf

    text = "\n".join(lines or ("Elektro Brandt GmbH", "Rechnung 2026-0473", "Wartung Heizung Ferienwohnung",
                               "Rechnungsbetrag 999,99 EUR"))
    pdf = pikepdf.open(io.BytesIO(make_pdf([text])))
    spec = pikepdf.AttachedFileSpec(pdf, xml if xml is not None else cii(), mime_type="text/xml",
                                    description="Factur-X invoice")
    pdf.attachments[name] = spec
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


ENTITIES = b"""<?xml version="1.0"?>
<!DOCTYPE Invoice [<!ENTITY secret SYSTEM "file:///etc/passwd">]>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"><cbc:ID>&secret;</cbc:ID></Invoice>
"""
EXTERNAL_DTD = b"""<?xml version="1.0"?>
<!DOCTYPE Invoice SYSTEM "http://example.com/evil.dtd">
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><ID>1</ID></Invoice>
"""
BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><ID>&lol3;</ID></Invoice>
"""


def deep(levels: int = 300) -> bytes:
    """A UBL root with a tree ``levels`` deep inside it."""
    return (b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><ID>1</ID>'
            + b"<a>" * levels + b"x" + b"</a>" * levels + b"</Invoice>")


def with_attributes(count: int) -> bytes:
    """A UBL invoice whose root carries ``count`` attributes (a hostile XML: libxml2 compares them with each other)."""
    marks = b" ".join(b'a%d="1"' % number for number in range(count))
    return (b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" ' + marks
            + b"><ID>1</ID></Invoice>")


def with_namespaces(count: int) -> bytes:
    """A UBL invoice whose root declares ``count`` namespaces."""
    marks = b" ".join(b'xmlns:p%d="urn:example:%d"' % (number, number) for number in range(count))
    return (b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" ' + marks
            + b"><ID>1</ID></Invoice>")


def wide(children: int) -> bytes:
    """A UBL invoice with ``children`` empty siblings under its root."""
    return (b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><ID>1</ID>'
            + b"<a/>" * children + b"</Invoice>")
