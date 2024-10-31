from typing import Union

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from .dns_manager import ZoneManager

app = FastAPI()
templates = Jinja2Templates(directory="templates/html/")
zonemgr = ZoneManager()

TESTING = True

@app.get('/', response_class=HTMLResponse)
def read_root(request: Request):
    username = request.headers.get('REMOTE_USER')
    if TESTING:
        username = 'user'
    if not username:
        return 'LANDING PAGE: not registered.'
    return templates.TemplateResponse(
        request=request, name="index.html", context={"username": username}
    )

@app.get('/zone_file', response_class=PlainTextResponse)
def read_user_zone(request: Request):
    username = request.headers.get('REMOTE_USER')
    if TESTING:
        username = 'user'
    if not username:
        return PlainTextResponse('', status_code=401)
    try:
        zone = zonemgr.get_user_zonefile(username)
        return zone
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/reset_zone')
def reset_zone(request: Request):
    username = request.headers.get('REMOTE_USER')
    if not username:
        return {'ERROR': 'Unknown user'}
    zonemgr.reset_user_zonefile()

@app.get('/items/{item_id}')
def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}
