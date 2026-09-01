import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.pdf_generator import amount_in_words, generate_pdf


class PdfTests(unittest.TestCase):
    def test_amount_words(self):
        self.assertEqual(
            amount_in_words(Decimal("28442.40")),
            "UAE Dirham Twenty Eight Thousand Four Hundred Forty Two and Forty Fils Only",
        )

    def test_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {"document_type":"tax_invoice", "document_number":"JNA_S_0001",
                    "date":"01-Sep-2026", "client_name":"Sample Client LLC",
                    "address":"Dubai, UAE", "client_trn":"100000000000003",
                    "transaction_type":"sales", "description":"Commission for Unit 101",
                    "note":"Payment received.", "amount":"27088.00", "vat_rate":5}
            output = generate_pdf(data, root / "sample.pdf")
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
