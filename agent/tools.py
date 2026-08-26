"""Constrói LangChain tools a partir dos services.

Cada tool é um wrapper sobre o service correspondente.
"""
from typing import Optional

from langchain_core.tools import tool

from services.expense_service import ExpenseService
from services.income_service import IncomeService


def build_tools(
    expense_service: ExpenseService,
    income_service: IncomeService | None = None,
) -> list:
    """Constrói lista de tools LangChain injetadas com os services.

    Args:
        expense_service: ExpenseService já inicializado com conn e user_id
        income_service: IncomeService já inicializado com conn e user_id (opcional)

    Returns:
        Lista de tools prontas para bind no LLM
    """

    @tool
    def record_expense(
        amount: float,
        description: str,
        category: str,
        method: str,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Registra um gasto no banco de dados financeiro pessoal.

        Args:
            amount: Valor do gasto em reais (ex: 55.90)
            description: Descrição do gasto (ex: "almoço no restaurante")
            category: Categoria do gasto (deve ser uma das categorias válidas)
            method: Método de pagamento — use list_payment_methods para ver os disponíveis
            expense_date: Data do gasto no formato YYYY-MM-DD (padrão: hoje)
        """
        return expense_service.record_expense(amount, description, category, method, expense_date)

    @tool
    def query_expenses(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        method: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """Consulta gastos ativos com filtros opcionais.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            category: Filtrar por categoria específica
            method: Filtrar por método de pagamento
            keyword: Palavra-chave para busca textual na descrição
        """
        return expense_service.query_expenses(start_date, end_date, category, method, keyword)

    @tool
    def get_summary(
        start_date: str,
        end_date: str,
        group_by: str = "category",
    ) -> dict:
        """Retorna resumo de gastos agrupados por dimensão.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            group_by: Dimensão de agrupamento: 'category', 'method', 'day' ou 'month'
        """
        return expense_service.get_summary(start_date, end_date, group_by)

    @tool
    def list_categories() -> list[str]:
        """Retorna a lista de categorias de gastos disponíveis."""
        return expense_service.list_categories()

    @tool
    def list_payment_methods() -> list[str]:
        """Retorna a lista de métodos de pagamento disponíveis."""
        return expense_service.list_payment_methods()

    @tool
    def create_payment_method(name: str, confirmed: bool) -> dict:
        """Cria um novo método de pagamento definido pelo usuário.

        ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.
        Métodos do sistema (is_system=1) não podem ser substituídos.

        Args:
            name: Nome do novo método (será normalizado para lowercase)
            confirmed: True apenas se o usuário confirmou explicitamente agora
        """
        return expense_service.create_payment_method(name, confirmed)

    @tool
    def create_category(name: str, confirmed: bool) -> dict:
        """Cria uma nova categoria de gastos definida pelo usuário.

        ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.
        Categorias do sistema (is_system=1) não podem ser substituídas; esta tool só cria
        categorias novas (is_system=0).

        Args:
            name: Nome da nova categoria (será normalizado para title case)
            confirmed: True apenas se o usuário confirmou explicitamente agora
        """
        return expense_service.create_category(name, confirmed)

    @tool
    def find_expense_candidates(
        keyword: str,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Busca registros candidatos para edição ou exclusão.

        Use esta tool ANTES de delete_expense ou update_expense.

        - Com expense_date: retorna registros daquela data que contêm o keyword.
        - Sem expense_date: retorna registros da DATA MAIS RECENTE que contém o keyword.

        Args:
            keyword: Palavra-chave da descrição (ex: "almoço", "uber", "farmácia")
            expense_date: Data em YYYY-MM-DD. Só informe se o usuário mencionou data específica.
        """
        return expense_service.find_expense_candidates(keyword, expense_date)

    @tool
    def delete_expense(expense_id: int, confirmed: bool) -> dict:
        """Exclui um único registro de gasto (soft delete — dado preservado no banco).

        Use após identificar o registro com find_expense_candidates.
        O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

        Args:
            expense_id: ID único do registro a ser excluído
            confirmed: gerenciado pelo sistema — não altere manualmente
        """
        return expense_service.delete_expense(expense_id, confirmed)

    @tool
    def update_expense(
        expense_id: int,
        confirmed: bool,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        method: Optional[str] = None,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Atualiza campos de um único registro de gasto.

        Use após identificar o registro com find_expense_candidates.
        O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

        Args:
            expense_id: ID único do registro a ser atualizado
            confirmed: gerenciado pelo sistema — não altere manualmente
            amount: Novo valor em reais (opcional)
            description: Nova descrição (opcional)
            category: Nova categoria (opcional)
            method: Novo método de pagamento (opcional)
            expense_date: Nova data em YYYY-MM-DD (opcional)
        """
        return expense_service.update_expense(
            expense_id, confirmed, amount, description, category, method, expense_date
        )

    tools = [
        record_expense,
        query_expenses,
        get_summary,
        list_categories,
        list_payment_methods,
        create_payment_method,
        create_category,
        find_expense_candidates,
        delete_expense,
        update_expense,
    ]

    if income_service is None:
        return tools

    @tool
    def record_income(
        amount: float,
        description: str,
        category: str,
        income_date: Optional[str] = None,
    ) -> dict:
        """Registra um ganho/receita no banco de dados.

        Args:
            amount: Valor do ganho em reais (ex: 5000.00)
            description: Descrição do ganho (ex: "Salário agosto")
            category: Categoria do ganho — use list_income_categories para ver as disponíveis
            income_date: Data do ganho no formato YYYY-MM-DD (padrão: hoje)
        """
        return income_service.record_income(amount, description, category, income_date)

    @tool
    def query_incomes(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """Consulta ganhos ativos com filtros opcionais.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            category: Filtrar por categoria específica
            keyword: Palavra-chave para busca textual na descrição
        """
        return income_service.query_incomes(start_date, end_date, category, keyword)

    @tool
    def get_income_summary(
        start_date: str,
        end_date: str,
        group_by: str = "category",
    ) -> dict:
        """Retorna resumo de ganhos agrupados por dimensão.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            group_by: Dimensão de agrupamento: 'category', 'day' ou 'month'
        """
        return income_service.get_income_summary(start_date, end_date, group_by)

    @tool
    def list_income_categories() -> list[str]:
        """Retorna a lista de categorias de ganho disponíveis."""
        return income_service.list_income_categories()

    @tool
    def create_income_category(name: str, confirmed: bool) -> dict:
        """Cria uma nova categoria de ganho definida pelo usuário.

        ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.

        Args:
            name: Nome da nova categoria (será normalizado para title case)
            confirmed: True apenas se o usuário confirmou explicitamente agora
        """
        return income_service.create_income_category(name, confirmed)

    @tool
    def find_income_candidates(
        keyword: str,
        income_date: Optional[str] = None,
    ) -> dict:
        """Busca registros de ganho candidatos para edição ou exclusão.

        Use esta tool ANTES de delete_income ou update_income.

        Args:
            keyword: Palavra-chave da descrição (ex: "salário", "freela")
            income_date: Data em YYYY-MM-DD. Só informe se o usuário mencionou data específica.
        """
        return income_service.find_income_candidates(keyword, income_date)

    @tool
    def delete_income(income_id: int, confirmed: bool) -> dict:
        """Exclui um único registro de ganho (soft delete).

        O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

        Args:
            income_id: ID único do registro a ser excluído
            confirmed: gerenciado pelo sistema — não altere manualmente
        """
        return income_service.delete_income(income_id, confirmed)

    @tool
    def update_income(
        income_id: int,
        confirmed: bool,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        income_date: Optional[str] = None,
    ) -> dict:
        """Atualiza campos de um único registro de ganho.

        O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

        Args:
            income_id: ID único do registro a ser atualizado
            confirmed: gerenciado pelo sistema — não altere manualmente
            amount: Novo valor em reais (opcional)
            description: Nova descrição (opcional)
            category: Nova categoria (opcional)
            income_date: Nova data em YYYY-MM-DD (opcional)
        """
        return income_service.update_income(
            income_id, confirmed, amount, description, category, income_date
        )

    tools.extend([
        record_income,
        query_incomes,
        get_income_summary,
        list_income_categories,
        create_income_category,
        find_income_candidates,
        delete_income,
        update_income,
    ])

    return tools
