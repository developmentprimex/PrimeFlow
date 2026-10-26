"""Normal PrimeFlow user login; no credentials stored on disk."""
from urllib.parse import urlsplit, urlunsplit
import httpx


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message);self.status = status


def safe_base_url(value):
    url = urlsplit(value.strip())
    if (url.scheme not in ('https','http') or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ('','/')):
        raise ValueError('Vendos adresën HTTPS të PrimeFlow, pa rrugë ose kredenciale.')
    if url.scheme != 'https' and url.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Lidhja me PrimeFlow kërkon HTTPS.')
    return urlunsplit((url.scheme,url.netloc,'','',''))


class PrimeFlowClient:
    def __init__(self, base_url, transport=None):
        self.base_url = safe_base_url(base_url)
        self.http = httpx.Client(base_url=self.base_url+'/api', follow_redirects=False,
            timeout=httpx.Timeout(150, connect=15, write=60, pool=15), transport=transport, trust_env=False)
        self.token = None;self.user = None;self.frontend_url = None

    def call(self, method, path, **kwargs):
        headers = kwargs.pop('headers', {})
        if self.token:headers = {**headers,'Authorization':'Bearer '+self.token}
        response = self.http.request(method, self.base_url+'/api'+path, headers=headers, **kwargs)
        if response.status_code == 401 and self.token:
            refresh = self.http.post(self.base_url+'/api/auth/refresh')
            if refresh.status_code == 200:
                self.token = refresh.json()['access_token']
                response = self.http.request(method, self.base_url+'/api'+path,
                    headers={**headers,'Authorization':'Bearer '+self.token}, **kwargs)
        if not response.is_success:
            try:message = response.json().get('detail','PrimeFlow nuk e përfundoi kërkesën.')
            except ValueError:message = 'PrimeFlow nuk është i disponueshëm.'
            raise APIError(response.status_code, str(message)[:500])
        return response.json()

    def login(self, email, password):
        result = self.call('POST','/auth/login',json={'email':email,'password':password},timeout=30)
        self.token = result['access_token']
        self.user = self.call('GET','/auth/me',timeout=30)
        capabilities = self.call('GET','/mira-desktop/capabilities',timeout=30)
        if not capabilities.get('enabled'):raise APIError(503,'Mira për Windows nuk është aktivizuar në server.')
        self.frontend_url = safe_base_url(capabilities.get('frontend_url') or self.base_url)
        return self.user

    def create(self, item):
        return self.call('POST','/mira-desktop/sessions',json={'id':item['id'],
            'title':item['title'],'consent_acknowledged':True})

    def upload(self, item, seq, wav):
        start,end = item['segments'][seq]
        return self.call('POST',f"/mira-desktop/sessions/{item['id']}/segments/{seq}",
            params={'start_ms':start,'end_ms':end},content=wav,headers={'Content-Type':'audio/wav'})

    def finish(self, item):
        return self.call('POST',f"/mira-desktop/sessions/{item['id']}/finish",
            json=item.get('finish_spec') or {'segment_count':item['segment_count'],'partial':item['partial']},timeout=900)

    def close(self):
        try:
            if self.token:self.http.post(self.base_url+'/api/auth/logout',timeout=10)
        except httpx.HTTPError:pass
        self.token = None;self.http.close()
