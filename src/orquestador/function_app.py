import json
import logging
from datetime import datetime

import azure.functions as func
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agents import organize

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "ok", "service": "orquestador", "phase": 1}),
        mimetype="application/json",
    )


class Dinner(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    mode: str = "mcp"
    near: str = Field(min_length=1, max_length=100)
    people: int = Field(ge=1, le=20)
    max_per_head: float = Field(gt=0, le=1000)
    when: str = Field(min_length=16, max_length=40)

    @field_validator("when")
    @classmethod
    def explicit_datetime(cls, value: str) -> str:
        if "T" not in value:
            raise ValueError("Incluye fecha y hora ISO 8601.")
        datetime.fromisoformat(value)
        return value

    @field_validator("near")
    @classmethod
    def nonblank_zone(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Indica una zona.")
        return value.strip()


@app.route(route="cena", methods=["POST"])
async def cena(req: func.HttpRequest) -> func.HttpResponse:
    try:
        dinner = Dinner.model_validate(req.get_json())
    except (ValueError, ValidationError):
        logging.warning("Peticion de cena invalida.")
        return func.HttpResponse(
            json.dumps({"error": "JSON invalido: requiere near, people (1-20), max_per_head y when ISO con hora."}),
            status_code=400, mimetype="application/json",
        )
    if dinner.mode != "mcp":
        logging.warning("Modo de cena no implementado.")
        return func.HttpResponse(
            json.dumps({"error": "Solo mode=mcp esta implementado en fase 2."}),
            status_code=400, mimetype="application/json",
        )
    result = await organize(dinner.near, dinner.people, dinner.max_per_head, dinner.when)
    return func.HttpResponse(
        json.dumps(result), status_code=409 if result.get("status") == "unavailable" else 200,
        mimetype="application/json",
    )
