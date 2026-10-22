import csv
import io
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

import mistralai.workflows as workflows


class EssaibfRoutineInput(BaseModel):
    """Demande de telechargement d'un fichier structure comme essaibf.csv."""

    file_name: str = Field(default="essaibf.csv", description="Nom du fichier source, ex. essaibf.csv")
    csv_content: str = Field(description="Contenu complet du CSV (separateur point-virgule, encodage UTF-8)")
    request: str = Field(
        default="Produire un fichier de sortie pret a l'emploi",
        description="Demande associee au telechargement",
    )


def _to_decimal(raw: str) -> Decimal | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if cleaned in ("", "-"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _fmt(value: Decimal) -> str:
    return str(value).replace(".", ",")


@workflows.activity()
async def parse_and_summarize(csv_content: str) -> dict:
    reader = csv.reader(io.StringIO(csv_content), delimiter=";")
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("CSV vide ou illisible")

    header = [cell.strip() for cell in rows[0]]
    data = rows[1:]

    lower = {name.lower(): idx for idx, name in enumerate(header)}
    idx_debit = lower.get("debit")
    idx_credit = lower.get("credit")
    idx_categorie = lower.get("categorie")
    idx_date = lower.get("date operation") or lower.get("date de comptabilisation")
    idx_libelle = lower.get("libelle simplifie")

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    categories: dict = {}
    parsed_rows = []

    for row in data:
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        debit = _to_decimal(row[idx_debit]) if idx_debit is not None else None
        credit = _to_decimal(row[idx_credit]) if idx_credit is not None else None
        debit = debit if debit is not None else Decimal("0")
        credit = credit if credit is not None else Decimal("0")
        total_debit += debit
        total_credit += credit

        categorie = row[idx_categorie].strip() if idx_categorie is not None else "Sans categorie"
        bucket = categories.setdefault(categorie, {"debit": Decimal("0"), "credit": Decimal("0")})
        bucket["debit"] += debit
        bucket["credit"] += credit

        parsed_rows.append(
            {
                "date": row[idx_date].strip() if idx_date is not None else "",
                "libelle": row[idx_libelle].strip() if idx_libelle is not None else "",
                "categorie": categorie,
                "montant": credit + debit,
            }
        )

    parsed_rows.sort(key=lambda r: r["date"])

    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["Date operation", "Libelle simplifie", "Categorie", "Montant"])
    for r in parsed_rows:
        writer.writerow([r["date"], r["libelle"], r["categorie"], _fmt(r["montant"])])

    cat_lines = []
    for cat, v in sorted(categories.items()):
        cat_lines.append(
            {
                "categorie": cat,
                "total_debit": _fmt(v["debit"]),
                "total_credit": _fmt(v["credit"]),
                "solde": _fmt(v["credit"] + v["debit"]),
            }
        )

    return {
        "rows": len(data),
        "columns": len(header),
        "header": header,
        "total_debit": _fmt(total_debit),
        "total_credit": _fmt(total_credit),
        "balance": _fmt(total_credit + total_debit),
        "categories": cat_lines,
        "output_csv": out.getvalue(),
    }


@workflows.workflow.define(
    name="essaibf-routine",
    workflow_display_name="Routine essaibf",
    workflow_description="Routine d'entree : une demande de telechargement d'un fichier structure comme essaibf.csv. Produit un CSV de sortie normalise pret a l'emploi, avec resume (lignes, colonnes, debits, credits, par categorie).",
)
class EssaibfRoutine:
    @workflows.workflow.entrypoint
    async def run(self, input: EssaibfRoutineInput) -> dict:
        summary = await parse_and_summarize(input.csv_content)
        base = input.file_name.rsplit(".", 1)[0]
        return {
            "status": "ok",
            "request": input.request,
            "input_file": input.file_name,
            "rows": summary["rows"],
            "columns": summary["columns"],
            "total_debit": summary["total_debit"],
            "total_credit": summary["total_credit"],
            "balance": summary["balance"],
            "categories": summary["categories"],
            "output_file_name": f"{base}_sortie.csv",
            "output_csv": summary["output_csv"],
        }
