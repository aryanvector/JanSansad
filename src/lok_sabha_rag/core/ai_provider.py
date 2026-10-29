"""Server-side text generation providers. Credentials never reach the browser."""
import json
import os
import re
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener,HTTPRedirectHandler


class GenerationError(Exception):
    def __init__(self,message,code='provider_unavailable',status_code=503):
        super().__init__(message);self.code=code;self.status_code=status_code


def normalize_citation_groups(text,prefix):
    """Render grouped references as individual IDs for validation and links."""
    p=re.escape(prefix)
    pattern=rf'\[({p}\d+(?:\s*(?:,|;|and)\s*(?:{p})?\d+)+)\]'
    return re.sub(pattern,lambda m:' '.join(f'[{prefix}{n}]' for n in re.findall(r'\d+',m[1])),text)


def configuration():
    provider=os.getenv('AI_PROVIDER','auto').strip().lower()
    if provider=='auto':provider='gemini' if os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY') else 'openai'
    if provider=='gemini':
        model=os.getenv('GEMINI_MODEL','gemini-flash-lite-latest').removeprefix('models/')
        configured=bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'))
    else:
        model=os.getenv('OPENAI_MODEL','gpt-4o-mini');configured=bool(os.getenv('OPENAI_API_KEY'))
    return {'provider':provider,'model':model,'configured':configured,'configuration_only':True}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise GenerationError('The AI provider returned an unexpected redirect.')


def _gemini(system,user,model,max_tokens):
    key=os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not key:raise GenerationError('Gemini API key is not configured on the server.','not_configured')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',model):raise GenerationError('Invalid Gemini model configuration.','model_unavailable')
    payload={'systemInstruction':{'parts':[{'text':system}]},
        'contents':[{'role':'user','parts':[{'text':user}]}],
        'generationConfig':{'maxOutputTokens':max(4096,max_tokens)}}
    request=Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key})
    try:
        with build_opener(NoRedirect()).open(request,timeout=60) as response:raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise GenerationError('AI response exceeded its size limit.')
        data=json.loads(raw)
    except HTTPError as error:
        # Never surface upstream messages: they may contain credential fragments.
        status=error.code
        try:
            body=json.loads(error.read(16000));details=body.get('error',{}).get('details',[])
            reasons={x.get('reason') for x in details if isinstance(x,dict)}
        except (ValueError,UnicodeError):reasons=set()
        if status in (401,403) or 'API_KEY_INVALID' in reasons:
            raise GenerationError('Gemini rejected the key or project permissions. Check the server Gemini credentials.','authentication_failed',503) from None
        if status==429:
            raise GenerationError('Gemini quota or rate limit reached. Wait and try again, or check the Gemini project quota and billing.','rate_limit',429) from None
        if status==404:
            raise GenerationError('The configured Gemini model is unavailable for this key. Check GEMINI_MODEL.','model_unavailable',503) from None
        if status==400:
            raise GenerationError('Gemini rejected this request. Check the key, model and API project configuration.','request_rejected',503) from None
        raise GenerationError('Gemini is temporarily unavailable. Please try again later.','provider_unavailable',503) from None
    except (URLError,TimeoutError,OSError,ValueError):
        raise GenerationError('Gemini could not be reached or returned an unreadable response. Please try again.','provider_unavailable',503) from None
    candidates=data.get('candidates') or []
    if not candidates:raise GenerationError('Gemini returned no answer. The request may have been blocked by the provider.','no_answer',502)
    candidate=candidates[0];finish=candidate.get('finishReason')
    if finish not in (None,'STOP'):
        message='Gemini reached its response limit. Ask a narrower question.' if finish=='MAX_TOKENS' else 'Gemini could not complete this answer. Try a narrower question.'
        raise GenerationError(message,'incomplete_answer',502)
    text='\n'.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought')).strip()
    if not text:raise GenerationError('Gemini returned no usable answer.','no_answer',502)
    return text


def generate(system,user,max_tokens=2048,task='parliament'):
    config=configuration()
    if config['provider']=='gemini':return _gemini(system,user,config['model'],max_tokens)
    if config['provider']!='openai':raise GenerationError('Unsupported AI_PROVIDER configuration.','not_configured')
    if not config['configured']:raise GenerationError('AI API credentials are not configured. Document search remains available.','not_configured')
    from openai import OpenAI
    model=os.getenv('BILL_QA_MODEL',config['model']) if task=='bill' else config['model']
    try:
        response=OpenAI(timeout=60,max_retries=0).responses.create(model=model,instructions=system,
            input=[{'role':'user','content':user}],max_output_tokens=max_tokens,store=False)
        if getattr(response,'status',None)=='incomplete':raise GenerationError('The AI answer was incomplete. Ask a narrower question.','incomplete_answer',502)
        text=(getattr(response,'output_text',None) or '').strip()
        if not text:raise GenerationError('The AI provider returned no answer.','no_answer',502)
        return text
    except GenerationError:raise
    except Exception as error:
        if getattr(error,'status_code',None)==429:
            raise GenerationError('The AI provider quota or rate limit was reached. Check its API credits or try later.','rate_limit',429) from None
        if getattr(error,'status_code',None) in (401,403):
            raise GenerationError('The AI provider rejected the server credentials.','authentication_failed',503) from None
        raise GenerationError('The AI provider is unavailable. Retrieved documents remain available.','provider_unavailable',503) from None
