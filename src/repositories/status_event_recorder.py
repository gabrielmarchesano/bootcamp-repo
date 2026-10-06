from typing import Optional


def record_status_event(session, event_model, parent_attr: str, parent, from_status, to_status, reason: Optional[str]):
    """Grava uma linha de *_status_event pendurada NA RELAÇÃO com o pai.

    É o mesmo desenho do AccountRepository._record_status_event, escrito uma
    vez para as entidades novas (chave Pix, carteira, cartão, autorização,
    fatura). Pendurar pela relação, e não por id solto, é o que faz o
    SQLAlchemy gravar o pai ANTES do evento — senão a FK recusaria.
    """
    event = event_model()
    setattr(event, parent_attr, parent)
    event.from_status = from_status
    event.to_status = to_status
    event.reason = reason
    session.add(event)
    return event