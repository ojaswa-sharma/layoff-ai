from dataclasses import dataclass

@dataclass(frozen=True)
class botMessage:
    content : list
    role : str

@dataclass(frozen=True)
class botFact:
    fact : str
    fact_type : str

@dataclass(frozen=True)
class ZepData:
    user_id : str
    message : botMessage|botFact
    first_name : str = ""
    last_name : str = ""
    data_type : str = 'message'
    thread_id : str|None = None
