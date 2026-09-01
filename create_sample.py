from pathlib import Path
from app.pdf_generator import generate_pdf

root = Path(__file__).parent
data = {"document_type":"tax_invoice", "document_number":"JNA_S_0001", "date":"01-Sep-2026",
        "client_name":"SAMPLE CLIENT LLC", "address":"Dubai, UAE", "client_trn":"100000000000003",
        "transaction_type":"sales", "description":"Commission for Unit 101", "note":"Payment received.",
        "amount":"27088.00", "vat_rate":5}
generate_pdf(data, root / "sample_output_no_stamp.pdf")
