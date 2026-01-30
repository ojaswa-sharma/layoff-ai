from services.zep_service import ZepPersonalizer, botMessage

_personalizer = None

def get_personalizer():
    global _personalizer
    if _personalizer is None:
        _personalizer = ZepPersonalizer()
    
    return _personalizer