import json
from datetime import datetime

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def datetime_decoder(obj):
    if "date" in obj:
        obj["date"] = datetime.fromisoformat(obj["date"])
    return obj
