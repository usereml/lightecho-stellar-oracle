import importlib.util
from pathlib import Path
import sys
from typing import Optional

from flask import Flask, request, abort, Response
from flask_cors import CORS
from flask_httpauth import HTTPBasicAuth
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.xdr.sc_val_type import SCValType
from werkzeug.security import check_password_hash

mod_spec = importlib.util.spec_from_file_location(
    "local_settings", Path(__file__).resolve().parent / "local_settings.py"
)
assert mod_spec
local_settings = importlib.util.module_from_spec(mod_spec)
sys.modules["local_settings"] = local_settings
assert mod_spec.loader
mod_spec.loader.exec_module(local_settings)

app = Flask(__name__)
auth = HTTPBasicAuth()
CORS(app)


@auth.verify_password
def verify_password(username, password):
    if username in local_settings.API_USERS and check_password_hash(
        local_settings.API_USERS.get(username), password
    ):
        return username


def parse_sc_val(sc_val):
    if sc_val.u32 is not None:
        return sc_val.u32.uint32
    if sc_val.i32 is not None:
        return sc_val.i32.int32
    if sc_val.u64 is not None:
        return sc_val.u64.uint64
    if sc_val.i64 is not None:
        return sc_val.i64.int64
    if sc_val.u128 is not None:
        high = sc_val.u128.hi.uint64
        low = sc_val.u128.lo.uint64
        uint128 = (high << 64) | low
        return uint128
    if sc_val.i128 is not None:
        high = sc_val.i128.hi.uint64
        low = sc_val.i128.lo.uint64
        uint128 = (high << 64) | low
        return uint128
    raise ValueError("Could not parse sc_val")


@app.before_request
def handle_options():
    if request.method.lower() == "options":
        return Response()


def parse_symbol(symbol: Optional[str] = None):
    if symbol is None:
        abort(400, "Missing payload field 'symbol'")
    for base in ["XLM", "USD"]:
        xlm_parts = symbol.split(base)
        if len(xlm_parts) == 2:
            return xlm_parts[0], xlm_parts[1]
        else:
            usd_parts = symbol.split("USD")
            if len(usd_parts) == 2:
                return usd_parts[0], usd_parts[1]
            else:
                abort(400, "Invalid symbol, must begin with XLM or USD")


@app.route("/soroban/set-rate/", methods=["POST", "OPTIONS"])
@auth.login_required
def set_rate():
    if not request.json:
        return {"error": "This endpoint requires a JSON payload"}, 400
    base, quote = parse_symbol(request.json.get("symbol"))
    if base == "XLM":


@app.route("/soroban/parse-result-xdr/", methods=["POST", "OPTIONS"])
def soroban_parse_tx_response():
    if not request.json:
        return {"error": "This endpoint requires a JSON payload"}, 400
    xdr = request.json.get("xdr")
    if not xdr:
        return {"error": "Missing 'xdr' from JSON payload"}, 400
    transaction_meta = stellar_xdr.TransactionMeta.from_xdr(xdr)  # type: ignore
    # TODO handle multiple results[]
    results = transaction_meta.v3.tx_result.result.results[0].tr.invoke_host_function_result.success  # type: ignore
    result = results[0]
    common_resp = {"type": result.type}
    if result.type == SCValType.SCV_VOID:
        return common_resp
    elif result.type == SCValType.SCV_MAP:
        data = {}
        assert result.map is not None
        for entry in result.map.sc_map:
            key = entry.key.sym.sc_symbol.decode()
            value = parse_sc_val(entry.val)
            data[key] = value
        return {**common_resp, "value": data}
    elif result.type == SCValType.SCV_SYMBOL:
        return {**common_resp, "value": result.sym.sc_symbol.decode()}
    else:
        return {**common_resp, "error": "Unexpected result type"}, 400


@app.route("/soroban/int-to-uint64-high-low/", methods=["POST", "OPTIONS"])
def soroban_int_to_uint64():
    if not request.json:
        return {"error": "This endpoint requires a JSON payload"}, 400
    value = request.json.get("value")
    if not value:
        return {"error": "Missing 'value' from JSON payload"}, 400
    try:
        value_int = int(value)
    except (ValueError, TypeError):
        return {"error": "'value' must be a valid integer"}, 400
    high = (value_int >> 32) & 0xFFFFFFFF
    low = value_int & 0xFFFFFFFF
    return {"high": high, "low": low}
