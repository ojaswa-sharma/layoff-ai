from services.graphiti.graphiti_service import Personalizer

_personalizer = None

def get_graphitit_personalizer():
    global _personalizer
    if not _personalizer:
        _personalizer = Personalizer()
    return _personalizer