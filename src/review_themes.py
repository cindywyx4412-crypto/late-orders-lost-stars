"""
Rule-based theme tagging for Portuguese 1-2 star review comments.
Rules were drafted with an AI assistant (Claude), tuned on a 50-review dev sample,
and evaluated on a separate, manually labelled 60-review test sample (see outputs/).
"""
import re
import unicodedata

THEMES = {
    "not_received": r"nao (?:recebi|recebemos|chegou|foi entregue|foram entregues|veio|entregou|entregaram)"
                    r"|ainda nao (?:recebi|chegou|foi)|nunca (?:chegou|recebi)|aguardando|em transito|nao entregue"
                    r"|nada chegou|ate (?:hoje|hj|agora|o momento) nada",
    "late": r"atrasad|atraso|atrasou|prazo|demor",
    "wrong_or_missing_item": r"errad|faltando|faltou|faltam|incomplet|metade|parcial|quantidade"
                             r"|so (?:veio|recebi|chegou|entregou)|somente (?:1|um|uma)|apenas (?:um|uma|1|chegou)"
                             r"|veio (?:so|apenas)|chegou (?:um|1|so|somente|apenas)|entregou (?:um|1|so|somente|apenas)"
                             r"|outro produto|trocad|um dos (?:produtos|itens)|o outro nao",
    "defective_damaged": r"defeit|quebr|danific|amassad|nao funciona|parou de funcionar|rasgad|vazad|riscad"
                         r"|mal lacrad|avari|havaria|destruid",
    "quality_not_as_described": r"qualidade|falsa|falsific|nao e original|diferente|incompativel|nao era o que|nao corresponde",
    "refund_cancel_service": r"devol|reembols|estorn|dinheiro de volta|atendimento|cancel|sem resposta|nao responde|contato|retorno",
}
_COMPILED = {k: re.compile(v) for k, v in THEMES.items()}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def tag(text: str) -> set[str]:
    t = normalize(text or "")
    return {k for k, rx in _COMPILED.items() if rx.search(t)}
