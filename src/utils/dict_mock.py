"""DICT de mentirinha para chaves de FORA desta instituição.

As chaves da casa moram na tabela pix_key e são resolvidas pelo
repository. Para chave de outro banco, num sistema de verdade a consulta
iria ao DICT do BCB por um connector (src/connectors/). Até lá, quem faz
esse papel é esta tabela — o mesmo espírito das "chaves Pix mockadas" do
sandbox da QI. Chave que não está aqui nem na pix_key não existe (404).
"""

EXTERNAL_KEYS = {
    "fornecedor@externo.com": {
        "ispb": "60746948",
        "account_branch": "0452",
        "account_number": "370158",
        "account_digit": "1",
        "account_type": "CHECKING",
        "owner_name": "Fornecedor Externo LTDA",
        "owner_document": "32402502000135",
        "owner_person_type": "LEGAL",
    },
    "+5511988887777": {
        "ispb": "00360305",
        "account_branch": "1234",
        "account_number": "99887766",
        "account_digit": "5",
        "account_type": "SAVINGS",
        "owner_name": "Joana Externa",
        "owner_document": "39053344705",
        "owner_person_type": "NATURAL",
    },
}


def lookup_external(pix_key: str):
    return EXTERNAL_KEYS.get(pix_key)
