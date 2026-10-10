from pathlib import Path
from os import path, environ

root = Path(__file__).resolve().parents[1]

if not environ.get("APP_ENV") or environ.get("APP_ENV") == "local":
    from dotenv import load_dotenv

    load_dotenv(path.join(str(root), ".env"))

    if environ.get("SERVER_LOCALHOST") is None:
        environ["SERVER_LOCALHOST"] = "localhost"

# Formato de erro do base-service: todo erro da API volta com estes campos, e só eles.
ERROR_FIELDS = {"title", "description", "translation", "code"}
