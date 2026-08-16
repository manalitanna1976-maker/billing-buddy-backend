from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.config import get_settings
from app.models import Invoice
from app.services.num2words_inr import amount_in_words

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
# Autoescape HTML: invoice fields (customer name/address, product names, ...)
# are tenant-controlled free text rendered straight into this template. Without
# escaping, a crafted field can inject markup WeasyPrint will fetch server-side
# (e.g. <img src="http://internal-host/...">) -- an SSRF/HTML-injection vector.
_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


def _local_file_url(upload_dir_root: Path, served_path: str | None) -> str | None:
    """Resolve a served `/uploads/...` URL path (the API contract clients
    use) back to the on-disk file under upload_dir, for WeasyPrint to read
    directly via file://. storage.save_upload always prefixes URLs with
    the literal "/uploads/" regardless of the configured upload_dir name
    (see app/storage.py and the StaticFiles mount in app/main.py) — so we
    must strip that fixed URL prefix rather than concatenate it onto
    upload_dir, which would double the "uploads" segment and point at a
    path that was never written to disk.
    """
    if not served_path:
        return None
    relative = served_path.removeprefix("/uploads/")
    return f"file://{upload_dir_root / relative}"


def render_invoice_html(invoice: Invoice) -> str:
    """Render the invoice HTML (pre-PDF). Exposed separately from
    render_invoice_pdf so tests can assert on markup (e.g. the default
    logo fallback) without going through WeasyPrint's PDF encoding."""
    settings = get_settings()
    upload_root = Path(settings.upload_dir).resolve()

    # logo_url/signature_url already carry the correct extension (Task 5's
    # save_upload accepts .png/.jpg/.jpeg).
    template = _env.get_template("invoice.html")
    return template.render(
        invoice=invoice,
        business=invoice.business,
        customer=invoice.customer,
        line_items=invoice.line_items,
        amount_in_words=amount_in_words(invoice.grand_total),
        logo_path=_local_file_url(upload_root, invoice.business.logo_url),
        signature_path=_local_file_url(upload_root, invoice.business.signature_url),
    )


def render_invoice_pdf(invoice: Invoice) -> bytes:
    html = render_invoice_html(invoice)
    return HTML(string=html).write_pdf()
