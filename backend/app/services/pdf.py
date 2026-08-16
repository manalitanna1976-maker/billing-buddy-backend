from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.config import get_settings
from app.models import Invoice
from app.services.num2words_inr import amount_in_words

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


def render_invoice_pdf(invoice: Invoice) -> bytes:
    settings = get_settings()
    upload_root = Path(settings.upload_dir).resolve()

    # logo_url/signature_url already carry the correct extension (Task 5's
    # save_upload accepts .png/.jpg/.jpeg) — resolve them from upload_root
    # rather than hardcoding an extension.
    template = _env.get_template("invoice.html")
    html = template.render(
        invoice=invoice,
        business=invoice.business,
        customer=invoice.customer,
        line_items=invoice.line_items,
        amount_in_words=amount_in_words(invoice.grand_total),
        logo_path=f"file://{upload_root}{invoice.business.logo_url}" if invoice.business.logo_url else None,
        signature_path=f"file://{upload_root}{invoice.business.signature_url}" if invoice.business.signature_url else None,
    )
    return HTML(string=html).write_pdf()
