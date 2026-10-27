"""Aplicação web responsiva do Finanças IA.

Entrypoint: uvicorn web.main:app --host 0.0.0.0 --port 8080

Endpoints:
- GET  /                    → dashboard de despesas
- GET  /importar-fatura     → upload de fatura PDF
- POST /importar-fatura     → processa upload
- GET  /revisar-fatura/{id} → tela de conciliação
- POST /confirmar-fatura/{id} → confirma conciliação
- GET  /extrato-bancario    → entrada "Em breve"
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from database.setup import get_connection
from services.expense_service import ExpenseService
from services.statement_service import StatementService
from web.auth import _resolve_default_user, check_password, get_current_user

# Diretórios
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def run_migrations() -> None:
    """Aplica migrations pendentes."""
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="Finanças IA Web", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.web_session_secret,
    session_cookie="financas_session",
    max_age=3600 * 8,  # 8 horas
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _save_upload(file: UploadFile) -> Path:
    """Salva o arquivo enviado em disco e retorna o caminho."""
    suffix = Path(file.filename or "fatura.pdf").suffix
    dest = UPLOADS_DIR / f"stmt_{os.urandom(8).hex()}{suffix}"
    with open(dest, "wb") as f:
        f.write(file.file.read())
    return dest


def _get_expense_service(user: dict = Depends(get_current_user)):
    conn = get_connection()
    return ExpenseService(conn, user_id=user["id"])


def _get_statement_service(user: dict = Depends(get_current_user)):
    conn = get_connection()
    return StatementService(conn, user_id=user["id"])


# ─── Autenticação ────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if check_password(password):
        user = _resolve_default_user()
        request.session["user_id"] = user["id"]
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Senha inválida"}, status_code=401
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    service: ExpenseService = Depends(_get_expense_service),
    user: dict = Depends(get_current_user),
):
    from datetime import date

    today = date.today()
    start_of_month = today.replace(day=1)
    end_of_month = today

    summary_category = service.get_summary(
        start_date=start_of_month.isoformat(),
        end_date=end_of_month.isoformat(),
        group_by="category",
    )
    summary_method = service.get_summary(
        start_date=start_of_month.isoformat(),
        end_date=end_of_month.isoformat(),
        group_by="method",
    )
    summary_month = service.get_summary(
        start_date=(today.replace(month=1, day=1)).isoformat(),
        end_date=end_of_month.isoformat(),
        group_by="month",
    )

    categories = service.list_categories()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "summary_category": summary_category,
            "summary_method": summary_method,
            "summary_month": summary_month,
            "categories": categories,
            "current_month": today.strftime("%B/%Y"),
        },
    )


# ─── Importar fatura ─────────────────────────────────────────────────────────

@app.get("/importar-fatura", response_class=HTMLResponse)
async def import_statement_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(
        "import_statement.html", {"request": request, "user": user}
    )


@app.post("/importar-fatura")
async def import_statement(
    request: Request,
    file: UploadFile = File(...),
    card_last_four: str = Form(""),
    card_holder: str = Form(""),
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")

    dest = _save_upload(file)
    try:
        statement_id, statement = service.import_statement(
            dest,
            card_last_four=card_last_four or None,
            card_holder=card_holder or None,
        )
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Erro ao processar fatura: {e}")

    # Remove o arquivo após extração (dados já estão no banco)
    dest.unlink(missing_ok=True)

    # Se não informou cartão/titular e a fatura tem múltiplos, redireciona para seleção
    holders = statement.card_holders
    if len(holders) > 1 and not card_last_four:
        return templates.TemplateResponse(
            "select_holder.html",
            {
                "request": request,
                "user": user,
                "statement_id": statement_id,
                "holders": holders,
            },
        )

    return RedirectResponse(
        url=f"/revisar-fatura/{statement_id}?card_last_four={card_last_four or ''}",
        status_code=302,
    )


@app.get("/revisar-fatura/{statement_id}", response_class=HTMLResponse)
async def review_statement(
    request: Request,
    statement_id: int,
    card_last_four: str = "",
    card_holder: str = "",
    service: StatementService = Depends(_get_statement_service),
    expense_service: ExpenseService = Depends(_get_expense_service),
    user: dict = Depends(get_current_user),
):
    result = service.reconcile(
        statement_id,
        card_last_four=card_last_four or None,
        card_holder=card_holder or None,
    )
    categories = expense_service.list_categories()

    return templates.TemplateResponse(
        "review_statement.html",
        {
            "request": request,
            "user": user,
            "statement_id": statement_id,
            "card_last_four": card_last_four,
            "card_holder": card_holder,
            "only_on_statement": result.only_on_statement,
            "matched": result.matched,
            "ambiguous": result.ambiguous,
            "only_on_database": result.only_on_database,
            "warnings": result.warnings,
            "categories": categories,
        },
    )


@app.post("/confirmar-fatura/{statement_id}")
async def confirm_statement(
    request: Request,
    statement_id: int,
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    form = await request.form()

    def _to_int_list(key: str) -> list[int]:
        values = form.getlist(key)
        return [int(v) for v in values if v]

    insert_ids = _to_int_list("insert_ids")
    delete_ids = _to_int_list("delete_ids")
    update_pairs_raw = form.getlist("update_pairs")

    parsed_updates: list[tuple[int, int]] = []
    for pair in update_pairs_raw:
        try:
            tx_id, exp_id = pair.split(":")
            parsed_updates.append((int(tx_id), int(exp_id)))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Formato inválido: {pair}")

    # Valida e agrupa inserções por categoria
    inserts_by_category: dict[str, list[int]] = {}
    for tx_id in insert_ids:
        cat = form.get(f"category_{tx_id}")
        if not cat:
            raise HTTPException(
                status_code=400,
                detail=f"Selecione uma categoria para o lançamento {tx_id}.",
            )
        inserts_by_category.setdefault(cat, []).append(tx_id)

    summary = {
        "inserted": 0,
        "updated": 0,
        "deleted": 0,
        "errors": [],
    }

    if inserts_by_category:
        for category, tx_ids in inserts_by_category.items():
            partial = service.confirm_reconciliation(
                statement_id,
                insert_ids=tx_ids,
                update_pairs=parsed_updates,
                delete_ids=delete_ids,
                default_category=category,
            )
            summary["inserted"] += partial["inserted"]
            summary["updated"] += partial["updated"]
            summary["deleted"] += partial["deleted"]
            summary["errors"].extend(partial["errors"])
    else:
        partial = service.confirm_reconciliation(
            statement_id,
            insert_ids=[],
            update_pairs=parsed_updates,
            delete_ids=delete_ids,
            default_category="Outros",
        )
        summary["inserted"] = partial["inserted"]
        summary["updated"] = partial["updated"]
        summary["deleted"] = partial["deleted"]
        summary["errors"] = partial["errors"]

    request.session["flash"] = (
        f"Inseridos: {summary['inserted']}, Atualizados: {summary['updated']}, "
        f"Excluídos: {summary['deleted']}. Erros: {len(summary['errors'])}"
    )

    return RedirectResponse(url="/", status_code=302)


# ─── Extrato bancário (Em breve) ─────────────────────────────────────────────

@app.get("/extrato-bancario", response_class=HTMLResponse)
async def bank_statement_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(
        "coming_soon.html",
        {
            "request": request,
            "user": user,
            "title": "Importar extrato bancário",
            "message": "Em breve",
        },
    )
