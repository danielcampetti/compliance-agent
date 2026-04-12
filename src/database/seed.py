"""Populate the compliance database with realistic sample data."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.database.connection import get_db
from src.database.setup import create_tables

_TODAY = datetime(2025, 4, 12)


def _d(days_ago: int, hour: int = 10) -> str:
    dt = _TODAY - timedelta(days=days_ago)
    return dt.replace(hour=hour, minute=0, second=0).isoformat()


_TRANSACTIONS = [
    # --- Cash deposits above R$50,000 (5 total; 3 reported, 2 not) ---
    ("João Batista Silva",      "123.456.789-00", "deposito_especie",  55000.00, _d(5),   "Agência Centro SP",    "agencia",          True,  False, "Depósito em espécie acima do limite COAF"),
    ("Maria das Graças Santos", "234.567.890-11", "deposito_especie",  72000.00, _d(12),  "Agência Paulista",     "agencia",          True,  False, "Depósito em espécie acima do limite COAF"),
    ("Carlos Eduardo Oliveira", "345.678.901-22", "deposito_especie",  90000.00, _d(20),  "Agência Copacabana RJ","agencia",          True,  False, "Depósito em espécie acima do limite COAF"),
    # Not reported — compliance gap
    ("Ana Paula Ferreira",      "456.789.012-33", "deposito_especie",  61000.00, _d(8),   "Agência Paulista",     "agencia",          False, False, "NÃO REPORTADO — depósito acima do limite"),
    ("Roberto Alves Costa",     "567.890.123-44", "deposito_especie",  53500.00, _d(15),  "Agência Centro SP",    "caixa_eletronico", False, False, "NÃO REPORTADO — depósito acima do limite"),
    # --- PEP transactions (3) ---
    ("Deputado Marcos Vieira",  "678.901.234-55", "transferencia",     38000.00, _d(3),   "Agência Paulista",     "internet",         False, True,  "Transferência — cliente PEP"),
    ("Vereadora Lúcia Nunes",   "789.012.345-66", "pix",               15000.00, _d(7),   "Agência Copacabana RJ","app",              False, True,  "PIX — cliente PEP"),
    ("Senador Paulo Ramos",     "890.123.456-77", "deposito_especie",  45000.00, _d(25),  "Agência Centro SP",    "agencia",          False, True,  "Depósito — cliente PEP"),
    # --- Normal PIX transfers (10) ---
    ("Fernanda Rodrigues",      "901.234.567-88", "pix",                1200.00, _d(1),   "Agência Paulista",     "app",              False, False, None),
    ("Gustavo Lima",            "012.345.678-99", "pix",                3400.00, _d(2),   "Agência Centro SP",    "app",              False, False, None),
    ("Helena Carvalho",         "111.222.333-00", "pix",                 850.00, _d(4),   "Agência Copacabana RJ","app",              False, False, None),
    ("Igor Nascimento",         "222.333.444-11", "pix",                5600.00, _d(6),   "Agência Paulista",     "internet",         False, False, None),
    ("Juliana Moreira",         "333.444.555-22", "pix",                2100.00, _d(9),   "Agência Centro SP",    "app",              False, False, None),
    ("Kleber Souza",            "444.555.666-33", "pix",                7800.00, _d(11),  "Agência Copacabana RJ","internet",         False, False, None),
    ("Larissa Teixeira",        "555.666.777-44", "pix",                4200.00, _d(14),  "Agência Paulista",     "app",              False, False, None),
    ("Marcos Pereira",          "666.777.888-55", "pix",                9100.00, _d(18),  "Agência Centro SP",    "app",              False, False, None),
    ("Natália Gomes",           "777.888.999-66", "pix",                 620.00, _d(22),  "Agência Copacabana RJ","app",              False, False, None),
    ("Otávio Barbosa",          "888.999.000-77", "pix",               11000.00, _d(28),  "Agência Paulista",     "internet",         False, False, None),
    # --- Regular deposits under R$50,000 (15) ---
    ("Paula Cunha",             "999.000.111-88", "deposito_especie",  12000.00, _d(1,  9), "Agência Centro SP",    "agencia",        False, False, None),
    ("Quintino Araújo",         "000.111.222-99", "deposito_especie",  28000.00, _d(3,  14),"Agência Paulista",     "agencia",        False, False, None),
    ("Renata Borges",           "111.222.333-01", "deposito_especie",   8500.00, _d(5,  11),"Agência Copacabana RJ","agencia",        False, False, None),
    ("Sérgio Dias",             "222.333.444-12", "deposito_especie",  35000.00, _d(7,  10),"Agência Centro SP",    "caixa_eletronico",False,False, None),
    ("Tatiana Espírito Santo",  "333.444.555-23", "deposito_especie",  19000.00, _d(10, 15),"Agência Paulista",     "agencia",        False, False, None),
    ("Ulisses Faria",           "444.555.666-34", "deposito_especie",  42000.00, _d(13, 9), "Agência Copacabana RJ","agencia",        False, False, None),
    ("Vera Galvão",             "555.666.777-45", "deposito_especie",  21000.00, _d(16, 16),"Agência Centro SP",    "agencia",        False, False, None),
    ("Wagner Henriques",        "666.777.888-56", "deposito_especie",   6700.00, _d(19, 10),"Agência Paulista",     "caixa_eletronico",False,False, None),
    ("Ximena Iório",            "777.888.999-67", "deposito_especie",  14000.00, _d(23, 11),"Agência Copacabana RJ","agencia",        False, False, None),
    ("Yuri Jardim",             "888.999.000-78", "deposito_especie",  31000.00, _d(27, 14),"Agência Centro SP",    "agencia",        False, False, None),
    ("Zilda Keller",            "999.000.111-89", "deposito_especie",  47000.00, _d(33, 10),"Agência Paulista",     "agencia",        False, False, None),
    ("André Lopes",             "000.111.222-90", "deposito_especie",   9200.00, _d(40, 9), "Agência Copacabana RJ","agencia",        False, False, None),
    ("Beatriz Melo",            "111.222.334-01", "deposito_especie",  26000.00, _d(50, 15),"Agência Centro SP",    "agencia",        False, False, None),
    ("Caio Neves",              "222.333.445-12", "deposito_especie",  18500.00, _d(60, 10),"Agência Paulista",     "agencia",        False, False, None),
    ("Diana Oliveira",          "333.444.556-23", "deposito_especie",  39000.00, _d(70, 11),"Agência Copacabana RJ","agencia",        False, False, None),
    # --- Withdrawals (10) ---
    ("Eduardo Pinto",           "444.555.667-34", "saque_especie",     5000.00, _d(2,  8),  "Agência Centro SP",    "agencia",        False, False, None),
    ("Fábio Queiroz",           "555.666.778-45", "saque_especie",    12000.00, _d(4,  9),  "Agência Paulista",     "agencia",        False, False, None),
    ("Giovana Ramos",           "666.777.889-56", "saque_especie",     3500.00, _d(8,  10), "Agência Copacabana RJ","caixa_eletronico",False,False, None),
    ("Henrique Santos",         "777.888.990-67", "saque_especie",    25000.00, _d(11, 14), "Agência Centro SP",    "agencia",        False, False, None),
    ("Isabela Tavares",         "888.999.001-78", "saque_especie",     8000.00, _d(17, 11), "Agência Paulista",     "agencia",        False, False, None),
    # Unusual hours (madrugada)
    ("João Batista Silva",      "123.456.789-00", "saque_especie",    48000.00, _d(2,   2), "Agência Centro SP",    "caixa_eletronico",False,False, "Saque madrugada — padrão suspeito"),
    ("Ana Paula Ferreira",      "456.789.012-33", "saque_especie",    47500.00, _d(9,   3), "Agência Paulista",     "caixa_eletronico",False,False, "Saque madrugada — padrão suspeito"),
    ("Roberto Alves Costa",     "567.890.123-44", "saque_especie",    46000.00, _d(16,  1), "Agência Centro SP",    "caixa_eletronico",False,False, "Saque madrugada — estruturação suspeita"),
    ("Karla Uchoa",             "000.222.333-11", "saque_especie",     7200.00, _d(21, 10), "Agência Copacabana RJ","agencia",        False, False, None),
    ("Leonardo Vaz",            "111.333.444-22", "saque_especie",    16000.00, _d(30, 15), "Agência Paulista",     "agencia",        False, False, None),
    # --- Account transfers (7) ---
    ("Marina Xavier",           "222.444.555-33", "transferencia",    10000.00, _d(1,  11), "Agência Centro SP",    "internet",       False, False, None),
    ("Nilton Yamamoto",         "333.555.666-44", "transferencia",    25000.00, _d(3,  14), "Agência Paulista",     "internet",       False, False, None),
    ("Olga Zanini",             "444.666.777-55", "transferencia",     4500.00, _d(6,  10), "Agência Copacabana RJ","internet",       False, False, None),
    ("Pedro Abreu",             "555.777.888-66", "transferencia",    80000.00, _d(10, 16), "Agência Centro SP",    "internet",       False, False, None),
    ("Queila Braga",            "666.888.999-77", "transferencia",    15000.00, _d(14, 9),  "Agência Paulista",     "internet",       False, False, None),
    ("Rogério Castro",          "777.999.000-88", "transferencia",    33000.00, _d(20, 13), "Agência Copacabana RJ","internet",       False, False, None),
    ("Sabrina Duarte",          "888.000.111-99", "transferencia",     9800.00, _d(25, 11), "Agência Centro SP",    "app",            False, False, None),
]

_ALERTS_TEMPLATE = [
    {"type": "missing_coaf_report", "severity": "high",
     "desc": "Depósito em espécie de R$ 61.000,00 acima do limite COAF (R$ 50.000) não foi reportado. Cliente: Ana Paula Ferreira",
     "tx_idx": 3, "status": "open"},
    {"type": "missing_coaf_report", "severity": "high",
     "desc": "Depósito em espécie de R$ 53.500,00 acima do limite COAF (R$ 50.000) não foi reportado. Cliente: Roberto Alves Costa",
     "tx_idx": 4, "status": "open"},
    {"type": "pep_transaction", "severity": "medium",
     "desc": "Transferência de R$ 38.000,00 realizada por cliente PEP (Pessoa Exposta Politicamente): Deputado Marcos Vieira",
     "tx_idx": 5, "status": "open"},
    {"type": "unusual_pattern", "severity": "critical",
     "desc": "Estruturação suspeita: três saques em espécie próximos a R$ 50.000 pelo mesmo cliente (Roberto Alves Costa, CPF 567.890.123-44) em períodos distintos",
     "tx_idx": None, "status": "investigating"},
    {"type": "missing_coaf_report", "severity": "high",
     "desc": "Alerta anterior resolvido: depósito de João Batista Silva foi verificado e comunicação COAF confirmada",
     "tx_idx": 0, "status": "resolved"},
]


def seed_database() -> None:
    """Insert sample transactions and alerts. Idempotent — skips if data exists."""
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        if count > 0:
            return  # Already seeded

        conn.executemany(
            """INSERT INTO transactions
               (client_name, client_cpf, transaction_type, amount, date,
                branch, channel, reported_to_coaf, pep_flag, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            _TRANSACTIONS,
        )

        tx_ids = [row[0] for row in conn.execute("SELECT id FROM transactions ORDER BY id")]

        now = _TODAY.isoformat()
        for a in _ALERTS_TEMPLATE:
            tx_id = tx_ids[a["tx_idx"]] if a["tx_idx"] is not None else None
            resolved = now if a["status"] == "resolved" else None
            conn.execute(
                """INSERT INTO alerts
                   (transaction_id, alert_type, severity, description, status, created_at, resolved_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (tx_id, a["type"], a["severity"], a["desc"], a["status"], now, resolved),
            )


def init_db() -> None:
    """Create tables and seed if the DB file does not yet contain data."""
    create_tables()
    seed_database()


if __name__ == "__main__":
    init_db()
    with get_db() as conn:
        txn_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        alert_count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    print(f"Seeded {txn_count} transactions, {alert_count} alerts.")
