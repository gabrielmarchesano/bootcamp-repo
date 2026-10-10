from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import JobController


class JobResource:
    """Dispara um job agendado sob demanda (útil para testes ou reprocessamento).

    Protegido pelo INTERNAL-TOKEN como toda rota interna. O mesmo job roda
    pela linha de comando: `python -m jobs.<nome>` (src/jobs).
    """

    def on_post(self, job_name: str) -> JSONResponse:
        result = JobController().run(job_name)
        return JSONResponse(content=jsonable_encoder(result), status_code=http_status.HTTP_200_OK)
