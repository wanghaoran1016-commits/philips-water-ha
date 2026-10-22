"""Async cloud API, retaining upstream endpoints and request shapes."""
import aiohttp
import secrets
from .const import API_BASE_URL, APP_ID

class AuthError(Exception):
    """Session expired or credentials rejected."""
class APIError(Exception):
    """Cloud unavailable or incompatible response."""

def normalize_phone(phone):
    phone = phone.strip().replace(' ', '').replace('-', '')
    if phone.startswith('+'): return phone
    if phone.startswith('86') and len(phone) == 13: return '+' + phone
    if len(phone) == 11 and phone.startswith('1'): return '+86' + phone
    raise ValueError('Use an international phone number')

class DeermaAPIClient:
    def __init__(self, session, token=None):
        self.session, self.token = session, token

    async def request(self, method, path, *, data=None, params=None, auth=True):
        headers = {'app_id': APP_ID, 'accept-language': 'zh-CN', 'user-agent': 'okhttp/4.12.0'}
        if auth:
            if not self.token: raise AuthError('Authentication required')
            headers['authorization'] = 'Bearer ' + self.token
        try:
            async with self.session.request(method, API_BASE_URL + path, headers=headers,
                    json=data, params=params, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status in (401, 403): raise AuthError('Authentication required')
                response.raise_for_status()
                result = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise APIError('Cloud request failed') from None
        if not isinstance(result, dict): raise APIError('Unexpected cloud response')
        if result.get('code') in (401, 403, '401', '403'): raise AuthError('Authentication required')
        if result.get('code') != 0 and result.get('success') is not True:
            raise APIError('Cloud rejected request')
        return result.get('data')

    async def login(self, phone, pin, mode):
        data = await self.request('POST', '/api/app/session/', auth=False, data={
            'account': normalize_phone(phone), 'language': 'zh-CN', 'pin': pin,
            'registrationId': secrets.token_hex(9), 'system': 'android', 'verify': mode})
        if not isinstance(data, dict) or not data.get('accessToken'): raise AuthError('Login rejected')
        self.token = data['accessToken']
        return self.token

    async def request_captcha(self, phone):
        await self.request('POST', '/api/app/captcha', auth=False, data={
            'account': normalize_phone(phone), 'accountType': 'mobile', 'areaCode': '+86', 'captchaType': 'login'})

    async def devices(self):
        rooms = await self.request('GET', '/api/app/devices/')
        if not isinstance(rooms, list): raise APIError('Unexpected device list')
        return [device for room in rooms if isinstance(room, dict)
                for device in room.get('devices', []) if isinstance(device, dict)]

    async def mqtt_config(self, identifier):
        result = await self.request('GET', f'/api/app/devices/{identifier}/mqtt')
        if not isinstance(result, dict) or not result.get('host') or not result.get('clientID'):
            raise APIError('Missing MQTT configuration')
        return result

    async def total_water(self, identifier):
        data = await self.request('GET', f'/api/app/devices/{identifier}/totalWater', params={'product_type': 'WaterPurifier'})
        if not isinstance(data, dict): raise APIError('Unexpected usage response')
        return data
