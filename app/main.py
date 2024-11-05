import logging
import traceback

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic_settings import BaseSettings
from typing import Union

from .dns_manager import ZoneManager, BadZoneFile


class Settings(BaseSettings):
    root_domain: str = "example.com."
    testing_mode: bool = False
    testing_user: str = 'user'


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

settings = Settings()
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates/html/")
zonemgr = ZoneManager(settings.root_domain)

TESTING = False

@app.get('/', response_class=HTMLResponse)
async def read_root(request: Request):
    username = request.headers.get('remote-user')
    if not username and settings.testing_mode:
        username = settings.testing_user
    if not username:
        ctx = {
                "username": username,
              }
        return templates.TemplateResponse(request=request, name="index.html", context=ctx)
    ctx = {
            "username": username,
            "user_origin": zonemgr.user_zone_origin(username),
            "user_zone": zonemgr.get_user_zonefile(username),
            "testing_mode": settings.testing_mode,
          }
    return templates.TemplateResponse(request=request, name="user.html", context=ctx)

@app.get('/headers', response_class=PlainTextResponse)
async def read_root(request: Request):
    username = request.headers.get('remote-user')
    if not username and settings.testing_mode:
        username = settings.testing_user
    if not username:
        return JSONResponse(None, status_code=401)
    # TODO: check user belongs to group dns_admin
    headers = dict(request.headers)
    return JSONResponse(content=headers)

@app.get('/zonefile', response_class=PlainTextResponse)
def read_user_zone(request: Request):
    username = request.headers.get('remote-user')
    if not username and settings.testing_mode:
        username = settings.testing_user
    if not username:
        return PlainTextResponse('', status_code=401)
    try:
        zone = zonemgr.get_user_zonefile(username)
        return zone
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put('/zonefile')
async def set_user_zone(request: Request):
    username = request.headers.get('remote-user')
    if not username and settings.testing_mode:
        username = settings.testing_user
    if not username:
        return PlainTextResponse('', status_code=401)
    data = await request.body()
    data_str = data.decode("utf-8")
    logger.info(f'Set zone for {username}:\n{data_str}')
    try:
        zonemgr.set_user_zonefile(username, data_str)
    except BadZoneFile as e:
        logger.error(f'Bad zone for {username}:\n{str(e)}')
        # logger.error(traceback.print_exc())
        raise HTTPException(status_code=400, detail={'error': 'Bad zone file', 'message': str(e)})
    except Exception as e:
        logger.error(f'Exception setting zone file for {username}:\n{str(e)}')
        # logger.error(traceback.print_exc())
        raise HTTPException(status_code=402, detail={'error': 'Internal error', 'message': str(e)})

