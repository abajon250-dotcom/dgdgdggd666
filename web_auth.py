import hashlib
import hmac
from urllib.parse import parse_qs
from config import BOT_TOKEN

def verify_telegram_auth(init_data: str) -> bool:
    try:
        params = parse_qs(init_data)
        hash_str = params.get('hash', [''])[0]
        if not hash_str:
            return False
        del params['hash']
        sorted_params = [f"{k}={v[0]}" for k, v in sorted(params.items())]
        data_check_string = "\n".join(sorted_params)
        secret_key = hmac.new(key=b"WebAppData", msg=BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
        computed_hash = hmac.new(key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
        return computed_hash == hash_str
    except:
        return False