from models import PixKey, PixKeyInquiry


class PixDTO:
    @staticmethod
    def key_to_dict(pix_key: PixKey) -> dict:
        return {
            "pix_key_id": str(pix_key.id),
            "account_id": str(pix_key.account_id),
            "key_type": pix_key.key_type,
            "key_value": pix_key.key_value,
            "status": pix_key.status.enumerator,
            "created_at": pix_key.created_at.isoformat(),
        }

    @staticmethod
    def inquiry_to_dict(inquiry: PixKeyInquiry) -> dict:
        """A resposta da consulta, nos campos da QI (consultar_chave_pix).

        O documento sai sempre mascarado; o `end_to_end_id` é o que o Pix
        por chave TEM de mandar, e vale até `expires_at`.
        """
        return {
            "pix_key": inquiry.pix_key,
            "key_type": inquiry.key_type,
            "end_to_end_id": inquiry.end_to_end_id,
            "ispb": inquiry.ispb,
            "account_branch": inquiry.account_branch,
            "account_number": inquiry.account_number,
            "account_digit": inquiry.account_digit,
            "account_type": inquiry.account_type,
            "owner_name": inquiry.owner_name,
            "owner_masked_document": inquiry.owner_masked_document,
            "owner_person_type": inquiry.owner_person_type,
            "on_us": inquiry.destination_account_id is not None,
            "expires_at": inquiry.expires_at.isoformat(),
        }