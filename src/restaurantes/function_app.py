import json
import logging
import math
from datetime import datetime
from uuid import uuid4

import azure.functions as func

from data import RESTAURANTS, WEEKDAYS

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "ok", "service": "restaurantes", "phase": 1}),
        mimetype="application/json",
    )


def arguments(context: str) -> dict:
    try:
        args = json.loads(context)["arguments"]
        if not isinstance(args, dict):
            raise ValueError("arguments debe ser un objeto.")
        people = args.get("people")
        if type(people) is not int or not 1 <= people <= 20:
            raise ValueError("people debe ser un entero entre 1 y 20.")
        return args
    except (KeyError, TypeError, ValueError):
        logging.warning("Argumentos MCP invalidos.")
        raise


@app.mcp_tool_trigger(
    arg_name="context", tool_name="search",
    description="Busca por zona, capacidad y precio del MENU, sin bebida. days contiene dias en ingles; [] significa sin plazas. No reserva.",
    tool_properties=json.dumps([
        {"propertyName": "near", "propertyType": "string", "description": "Zona de demo: zona-demo.", "isRequired": True},
        {"propertyName": "people", "propertyType": "integer", "description": "Numero de comensales (1-20).", "isRequired": True},
        {"propertyName": "max_per_head", "propertyType": "number", "description": "Maximo del menu por persona, EUR.", "isRequired": True},
    ]),
)
def search(context: str) -> str:
    args = arguments(context)
    near, maximum = args.get("near"), args.get("max_per_head")
    if not isinstance(near, str) or not near.strip():
        raise ValueError("near debe indicar una zona.")
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not math.isfinite(maximum) or maximum <= 0:
        raise ValueError("max_per_head debe ser un numero finito positivo.")
    return json.dumps({"restaurants": [
        r for r in RESTAURANTS
        if r["near"].casefold() == near.strip().casefold()
        and r["capacity"] >= args["people"] and r["menu"] <= maximum
    ], "currency": "EUR", "price_basis": "menu_excluding_drink"})


@app.mcp_tool_trigger(
    arg_name="context", tool_name="book",
    description="Reserva FICTICIA. Valida ID, dia disponible y capacidad; no persiste ni cobra.",
    tool_properties=json.dumps([
        {"propertyName": "restaurant_id", "propertyType": "string", "description": "ID devuelto por search.", "isRequired": True},
        {"propertyName": "when", "propertyType": "string", "description": "Fecha y hora ISO 8601 explicitas.", "isRequired": True},
        {"propertyName": "people", "propertyType": "integer", "description": "Numero de comensales (1-20).", "isRequired": True},
    ]),
)
def book(context: str) -> str:
    args = arguments(context)
    restaurant = next((r for r in RESTAURANTS if r["id"] == args.get("restaurant_id")), None)
    when = args.get("when")
    if not isinstance(when, str) or "T" not in when:
        raise ValueError("when debe incluir fecha y hora ISO 8601.")
    moment = datetime.fromisoformat(when)
    if restaurant is None or WEEKDAYS[moment.weekday()] not in restaurant["days"]:
        raise ValueError("Restaurante desconocido o sin disponibilidad ese dia.")
    if args["people"] > restaurant["capacity"]:
        raise ValueError("Capacidad insuficiente.")
    return json.dumps({
        "booking_id": str(uuid4()), "restaurant_id": restaurant["id"],
        "when": moment.isoformat(), "people": args["people"], "simulated": True,
        "menu_per_head": restaurant["menu"], "drink_per_head": restaurant["drink"],
        "currency": "EUR",
    })
