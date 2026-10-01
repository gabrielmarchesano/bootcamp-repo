from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator

TEF_FEE = 100


def send_tef(source_id: str, destination_id: str, amount: int, key: str = None):
    payload = PayloadGenerator.create_tef_payload(source_id, destination_id, amount)
    return RequestGenerator.POST_transfer(payload, key or str(uuid4()))


class TestTransferConcurrency:
    """Os testes que justificam a ordem global de lock.

    Os outros testes desta pasta mandam UMA requisição por vez, e por isso
    nunca pegariam os dois bugs mais caros de um banco: o deadlock e o
    gasto duplo. Estes mandam várias AO MESMO TEMPO.
    """

    def test_crossed_transfers_do_not_deadlock(self):
        """A→B e B→A disparadas juntas, 20 de cada. Sem a ordem de lock, isto trava.

        O dinheiro se conserva: tudo que saiu de um entrou no outro, menos
        as tarifas.
        """
        account_a = ObjectGenerator.create_active_account(initial_balance=100_000)
        account_b = ObjectGenerator.create_active_account(initial_balance=100_000)
        a, b = account_a["account_id"], account_b["account_id"]

        jobs = [(a, b, 1_000)] * 20 + [(b, a, 1_000)] * 20

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda job: send_tef(*job), jobs))

        statuses = [status for status, _ in results]
        assert statuses.count(201) == 40, statuses

        total_after = ObjectGenerator.balance_of(a) + ObjectGenerator.balance_of(b)
        assert total_after == 200_000 - 40 * TEF_FEE

    def test_parallel_debits_never_overdraw(self):
        """Saldo 1.000, dez TEFs de 300 (+100 de tarifa) ao mesmo tempo.

        Cabem exatamente duas (2 × 400 = 800). Se o saldo fosse lido antes
        do lock, várias leriam 1.000, várias aprovariam, e a conta
        terminaria negativa.
        """
        source = ObjectGenerator.create_active_account(initial_balance=1_000)
        destination = ObjectGenerator.create_active_account()

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(
                pool.map(lambda _: send_tef(source["account_id"], destination["account_id"], 300), range(10))
            )

        statuses = sorted(status for status, _ in results)
        assert statuses.count(201) == 2, statuses
        assert statuses.count(422) == 8, statuses
        assert ObjectGenerator.balance_of(source["account_id"]) == 200
        assert ObjectGenerator.balance_of(destination["account_id"]) == 600

    def test_double_click_moves_money_once(self):
        """A mesma chave de idempotência disparada 8 vezes ao mesmo tempo: um débito, um 201."""
        source = ObjectGenerator.create_active_account(initial_balance=10_000)
        destination = ObjectGenerator.create_active_account()
        key = str(uuid4())

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda _: send_tef(source["account_id"], destination["account_id"], 1_000, key), range(8))
            )

        statuses = sorted(status for status, _ in results)
        transfer_ids = {body["transfer_id"] for _, body in results}

        assert statuses == [200] * 7 + [201], statuses
        assert len(transfer_ids) == 1
        assert ObjectGenerator.balance_of(source["account_id"]) == 10_000 - 1_000 - TEF_FEE
