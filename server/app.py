import json
import os
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .data import EventSource, DataError
from .evidence import EvidenceStore, EvidenceError
from .tools import ToolService, definitions
from .chat import ChatService, ChatInput, ChatError

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
app = FastAPI(title='Marquee', docs_url=None, redoc_url=None)
origins = set(os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000').split(','))
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list({urlparse(x).hostname for x in origins if urlparse(x).hostname}))
source, store = EventSource(), EvidenceStore()
service = ToolService(source,store)
chat = ChatService(service, store)
buckets = {}

@app.middleware('http')
async def protect(request, call_next):
    if request.url.path.startswith(('/api','/mcp')):
        if request.headers.get('origin') and request.headers['origin'] not in origins:
            return JSONResponse({'error':'Origin not allowed.'},403)
        now = time.monotonic()
        # Forwarded client IPs are trusted only when an ingress proxy we control sets them.
        # The trusted proxy appends the real client last; earlier entries are client-spoofable.
        ip = request.client.host if request.client else 'unknown'
        if os.getenv('TRUST_FORWARDED_FOR') == '1':
            forwarded = request.headers.get('x-forwarded-for', '')
            if forwarded:
                ip = forwarded.rsplit(',', 1)[-1].strip() or ip
        for key in list(buckets):
            if not buckets[key] or buckets[key][-1] < now-60: del buckets[key]
        q = buckets.setdefault(ip,deque())
        while q and q[0] < now-60: q.popleft()
        if len(q) >= 120 or len(buckets) > 10000:
            return JSONResponse({'error':'Too many requests. Try again in a minute.'},429,headers={'Retry-After':'60'})
        q.append(now)
        if request.method == 'POST':
            # Bound actual body bytes, including chunked requests.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 24000: return JSONResponse({'error':'Request too large.'},413)
            request._body = bytes(body)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.exception_handler(EvidenceError)
async def evidence_error(request,exc):
    expired = str(exc).startswith('Session expired.')
    return JSONResponse({'error':str(exc)},401 if expired else 400)

@app.exception_handler(DataError)
async def data_error(request,exc):
    return JSONResponse({'error':str(exc)},502)

@app.get('/api/health')
async def health():
    return {'status':'ok','mode':source.mode,'credentials_configured':bool(os.getenv('SEATGEEK_CLIENT_ID'))}

@app.post('/api/session')
async def session():
    return {'session_id':store.create(),'mode':source.mode}

@app.get('/api/chat/status')
async def chat_status():
    extra = await chat.model.status() if hasattr(chat.model, 'status') else {'model': getattr(chat.model, 'label', None)}
    return {'configured':chat.model.configured(), **extra}

@app.post('/api/chat/message')
async def chat_message(request:Request):
    try:
        value = ChatInput.model_validate(await request.json())
        if not value.message.strip():
            raise ValueError('Empty message')
        return await chat.send(value, request.headers.get('X-Marquee-Session',''))
    except (ValidationError, ValueError):
        return JSONResponse({'error':'Enter a message and valid search dates.'},422)
    except ChatError as exc:
        return JSONResponse({'error':str(exc)},503)

@app.post('/api/{name}')
async def api_tool(name:str, request:Request):
    try:
        args = await request.json()
        return await service.call(name,args,request.headers.get('X-Marquee-Session',''))
    except (ValidationError, ValueError):
        return JSONResponse({'error':'Invalid request. Check the input fields and date range.'},422)

def rpc_error(identifier,code,message):
    return {'jsonrpc':'2.0','id':identifier,'error':{'code':code,'message':message}}

@app.get('/mcp')
async def no_stream():
    return Response(status_code=405,headers={'Allow':'POST'})

@app.post('/mcp')
async def mcp(request:Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(rpc_error(None,-32700,'Parse error'),400)
    if not isinstance(body,dict) or body.get('jsonrpc') != '2.0' or not isinstance(body.get('method'),str):
        return JSONResponse(rpc_error(None,-32600,'Invalid request'),400)
    method, identifier = body['method'], body.get('id')
    if 'id' not in body:
        return Response(status_code=202)
    if method == 'initialize':
        return {'jsonrpc':'2.0','id':identifier,'result':{'protocolVersion':'2025-03-26','capabilities':{'tools':{}},
                'serverInfo':{'name':'marquee','version':'0.1.0'},
                'instructions':'Use /api/session to obtain an X-Marquee-Session evidence token. Prices are aggregate statistics. Verify canonical statements before presenting a plan. Include the report and scope limits.'}}
    if method == 'ping': result = {}
    elif method == 'tools/list': result = {'tools':definitions()}
    elif method == 'tools/call':
        params = body.get('params',{})
        try:
            if not isinstance(params,dict): raise ValueError('Invalid parameters')
            value = await service.call(params.get('name'),params.get('arguments',{}),request.headers.get('X-Marquee-Session',''))
            result = {'content':[{'type':'text','text':json.dumps(value)}]}
        except (ValueError, ValidationError):
            return rpc_error(identifier,-32602,'Invalid tool or arguments')
        except EvidenceError as exc:
            if str(exc).startswith('Session expired.'):
                return JSONResponse({'error':str(exc)},401)
            result = {'isError':True,'content':[{'type':'text','text':str(exc)}]}
        except DataError as exc:
            result = {'isError':True,'content':[{'type':'text','text':str(exc)}]}
    else: return rpc_error(identifier,-32601,'Method not found')
    return {'jsonrpc':'2.0','id':identifier,'result':result}

dist = ROOT / 'web' / 'dist'
if dist.exists():
    app.mount('/',StaticFiles(directory=dist,html=True),name='web')
