"""Aplicação web responsiva do Finanças IA.

Entrypoint: uvicorn web.main:app --host 0.0.0.0 --port 8080

A conciliação oferece:
- Aprovação e ignorar em lotes transacionais e idempotentes
- Persistência de progresso, categorias e histórico
- Seleção de múltiplos cartões
- Preservação das descrições originais da fatura e do Telegram
- Sugestão automática de categoria pelo histórico e pelo agente
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from database.setup import get_connection
from services.expense_service import ExpenseService
from services.statement_service import StatementService
from web.auth import _resolve_default_user, check_password, get_current_user
from web.dashboard import build_dashboard_data

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def run_migrations() -> None:
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
    max_age=3600 * 8,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "fatura.pdf").suffix
    dest = UPLOADS_DIR / f"stmt_{os.urandom(8).hex()}{suffix}"
    with open(dest, "wb") as f:
        f.write(file.file.read())
    return dest


def _get_expense_service(user: dict = Depends(get_current_user)):
    conn = get_connection()
    try:
        yield ExpenseService(conn, user_id=user["id"])
    finally:
        conn.close()


def _get_statement_service(user: dict = Depends(get_current_user)):
    conn = get_connection()
    try:
        yield StatementService(conn, user_id=user["id"])
    finally:
        conn.close()


def _referer_or_dashboard(request: Request) -> str:
    return request.headers.get("referer") or "/"


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
def dashboard(
    request: Request,
    period: str | None = None,
    evolution_category: str | None = None,
    evolution_method: str | None = None,
    service: ExpenseService = Depends(_get_expense_service),
    statement_service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    try:
        data = build_dashboard_data(service, period, evolution_category, evolution_method)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pending = statement_service.get_pending_summary()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "dashboard_data": data,
            "pending": pending,
        },
        headers={"Cache-Control": "no-store"},
    )


# ─── Importar fatura ─────────────────────────────────────────────────────────

@app.get("/importar-fatura", response_class=HTMLResponse)
async def import_statement_page(
    request: Request,
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    return templates.TemplateResponse(
        "import_statement.html",
        {"request": request, "user": user, "pending": service.get_pending_summary()},
    )


@app.post("/importar-fatura")
async def import_statement(
    request: Request,
    file: UploadFile = File(...),
    selected_cards: list[str] = Form(default=[]),
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")

    dest = _save_upload(file)

    # Pré-processa para identificar cartões
    try:
        from services.statement_parser import parse_bradesco_statement
        preview = parse_bradesco_statement(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Erro ao ler fatura: {e}")

    cards = preview.card_holders
    if len(cards) > 1 and not selected_cards:
        # Armazena o caminho do PDF na sessão para reutilização
        request.session["pending_pdf_path"] = str(dest)
        return templates.TemplateResponse(
            "select_holder.html",
            {
                "request": request,
                "user": user,
                "holders": cards,
                "pending": service.get_pending_summary(),
            },
        )

    try:
        statement_id, statement, processed_cards = service.import_statement(
            dest,
            selected_cards=selected_cards or None,
        )
    except Exception as e:
        dest.unlink(missing_ok=True)
        request.session.pop("pending_pdf_path", None)
        raise HTTPException(status_code=400, detail=f"Erro ao processar fatura: {e}")

    dest.unlink(missing_ok=True)
    request.session.pop("pending_pdf_path", None)
    return RedirectResponse(url=f"/revisar-fatura/{statement_id}", status_code=302)


@app.get("/selecionar-cartoes", response_class=HTMLResponse)
async def select_cards_page(
    request: Request,
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    pending_path = request.session.get("pending_pdf_path")
    if not pending_path or not Path(pending_path).exists():
        return RedirectResponse(url="/importar-fatura", status_code=302)

    from services.statement_parser import parse_bradesco_statement
    preview = parse_bradesco_statement(pending_path)

    return templates.TemplateResponse(
        "select_holder.html",
        {
            "request": request,
            "user": user,
            "holders": preview.card_holders,
            "pending": service.get_pending_summary(),
        },
    )


@app.post("/selecionar-cartoes")
async def select_cards(
    request: Request,
    selected_cards: list[str] = Form(default=[]),
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    pending_path = request.session.get("pending_pdf_path")
    if not pending_path or not Path(pending_path).exists():
        return RedirectResponse(url="/importar-fatura", status_code=302)

    if not selected_cards:
        raise HTTPException(status_code=400, detail="Selecione pelo menos um cartão.")

    try:
        statement_id, statement, processed_cards = service.import_statement(
            pending_path,
            selected_cards=selected_cards,
        )
    except Exception as e:
        Path(pending_path).unlink(missing_ok=True)
        request.session.pop("pending_pdf_path", None)
        raise HTTPException(status_code=400, detail=f"Erro ao processar fatura: {e}")

    Path(pending_path).unlink(missing_ok=True)
    request.session.pop("pending_pdf_path", None)
    return RedirectResponse(url=f"/revisar-fatura/{statement_id}", status_code=302)


# ─── Revisar fatura ──────────────────────────────────────────────────────────

@app.get("/revisar-fatura/{statement_id}", response_class=HTMLResponse)
def review_statement(
    request: Request,
    statement_id: int,
    service: StatementService = Depends(_get_statement_service),
    expense_service: ExpenseService = Depends(_get_expense_service),
    user: dict = Depends(get_current_user),
):
    try:
        state = service.get_review_state(statement_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    categories = expense_service.list_categories()

    return templates.TemplateResponse(
        "review_statement.html",
        {
            "request": request,
            "user": user,
            "statement_id": statement_id,
            "review_data": {"state": state, "categories": categories},
            "pending": service.get_pending_summary(),
        },
        headers={"Cache-Control": "no-store"},
    )


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^(?:tx|expense):[1-9][0-9]*$")
    category: str | None = Field(default=None, max_length=200)
    expense_id: StrictInt | None = Field(default=None, gt=0)


class ReviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: Literal["new", "matched", "bank"]
    action: Literal["approve", "ignore"]
    items: list[ReviewItem] = Field(min_length=1, max_length=1000)
    request_id: str = Field(min_length=1, max_length=128)


class ReviewCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^(?:tx|expense):[1-9][0-9]*$")
    category: str = Field(max_length=200)


@app.get("/api/reconciliation/{statement_id}")
def reconciliation_state(
    statement_id: int,
    service: StatementService = Depends(_get_statement_service),
    expense_service: ExpenseService = Depends(_get_expense_service),
):
    try:
        state = service.get_review_state(statement_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(
        {"state": state, "categories": expense_service.list_categories()},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/reconciliation/{statement_id}/batch")
def review_batch(
    statement_id: int,
    batch: ReviewBatch,
    service: StatementService = Depends(_get_statement_service),
):
    try:
        result = service.review_batch(
            statement_id, batch.section, batch.action,
            [item.model_dump(exclude_unset=True) for item in batch.items], batch.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/api/reconciliation/{statement_id}/category")
def review_category(
    statement_id: int,
    selection: ReviewCategory,
    service: StatementService = Depends(_get_statement_service),
):
    try:
        result = service.update_review_category(statement_id, selection.id, selection.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({key: result[key] for key in ("success", "updated", "category")})


# ─── Aprovação individual ────────────────────────────────────────────────────

@app.post("/api/approve-insert/{tx_id}")
async def approve_insert(
    tx_id: int,
    category: str = Form(...),
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    result = service.approve_insert(tx_id, category=category)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@app.post("/api/approve-match/{tx_id}/{expense_id}")
async def approve_match(
    tx_id: int,
    expense_id: int,
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    result = service.approve_match(tx_id, expense_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@app.post("/api/approve-review/{expense_id}")
async def approve_review(
    expense_id: int,
    statement_id: int = Form(...),
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    result = service.approve_review(expense_id, statement_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@app.post("/api/reject/{tx_id}")
async def reject_tx(
    tx_id: int,
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    result = service.reject(tx_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@app.post("/api/update-category/{tx_id}")
async def update_category(
    tx_id: int,
    category: str = Form(...),
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    result = service.update_category(tx_id, category)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@app.get("/api/suggest-category/{tx_id}")
def suggest_category(
    tx_id: int,
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    from services.category_suggester import CategorySuggester

    tx_row = service.conn.execute(
        """SELECT st.statement_id FROM statement_transactions st
           JOIN card_statements cs ON cs.id = st.statement_id
           WHERE st.id = ? AND cs.user_id = ?""",
        (tx_id, user["id"]),
    ).fetchone()
    if not tx_row:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
    state = service.get_review_state(tx_row["statement_id"])
    item = next((item for item in state["items"] if item["tx_id"] == tx_id), None)
    if not item:
        raise HTTPException(status_code=409, detail="Lançamento já revisado.")
    if item["category"] or item["category_edited"] or item["section"] != "new":
        return JSONResponse({"category": item["category"]})

    category = CategorySuggester(service.conn, user["id"]).suggest(item["name"])
    if category:
        try:
            result = service.update_review_category(
                tx_row["statement_id"], item["id"], category, only_if_empty=True,
            )
            category = result["category"]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"category": category}, headers={"Cache-Control": "no-store"})


# ─── Extrato bancário (Em breve) ─────────────────────────────────────────────

@app.get("/extrato-bancario", response_class=HTMLResponse)
async def bank_statement_page(
    request: Request,
    service: StatementService = Depends(_get_statement_service),
    user: dict = Depends(get_current_user),
):
    return templates.TemplateResponse(
        "coming_soon.html",
        {
            "request": request,
            "user": user,
            "pending": service.get_pending_summary(),
            "title": "Importar extrato bancário",
            "message": "Em breve",
        },
    )
