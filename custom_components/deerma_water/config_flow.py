"""Password/SMS login and explicit device selection. No credentials retained."""
from time import monotonic

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .api_client import DeermaAPIClient, APIError, AuthError, normalize_phone
from .const import DOMAIN
from .protocol import device_id

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self):
        self.api = None
        self.phone = None
        self.mode = None
        self.devices = []
        self.reauth_entry = None
        self.last_sms_sent = None

    async def async_step_user(self, user_input=None):
        if self.api is None:
            self.api = DeermaAPIClient(async_get_clientsession(self.hass))
        errors = {}
        if user_input:
            try:
                self.phone = normalize_phone(user_input['phone'])
                self.mode = user_input['login_type']
                if self.mode == 'captcha':
                    if self.last_sms_sent is not None and monotonic() - self.last_sms_sent < 60:
                        return await self.async_step_credentials({'action': 'resend'})
                    await self._send_sms()
                return await self.async_step_credentials()
            except (APIError, AuthError, ValueError):
                errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='user', data_schema=vol.Schema({
            vol.Required('phone', default=self.phone or ''): str,
            vol.Required('login_type', default=self.mode or 'password'): vol.In(['password', 'captcha'])}), errors=errors)

    async def _send_sms(self):
        """Only record successful sends; keep cooldown across navigation."""
        await self.api.request_captcha(self.phone)
        self.last_sms_sent = monotonic()

    async def async_step_credentials(self, user_input=None):
        errors = {}
        if user_input:
            action = user_input.get('action', 'login')
            if action == 'cancel':
                return self.async_abort(reason='user_cancelled')
            if action == 'back':
                return await self.async_step_user()
            if action == 'resend':
                if self.mode != 'captcha':
                    errors['base'] = 'cannot_connect'
                elif self.last_sms_sent is not None and monotonic() - self.last_sms_sent < 60:
                    errors['base'] = 'sms_cooldown'
                else:
                    try:
                        await self._send_sms()
                    except (APIError, AuthError, ValueError):
                        errors['base'] = 'sms_send_failed'
            elif not user_input.get('pin', '').strip():
                errors['pin'] = 'pin_required'
            else:
                try:
                    await self.api.login(self.phone, user_input['pin'], self.mode)
                    self.devices = [d for d in await self.api.devices() if device_id(d)]
                    if not self.devices:
                        errors['base'] = 'no_devices'
                    else:
                        return await self.async_step_device()
                except AuthError:
                    errors['base'] = 'invalid_auth'
                except (APIError, ValueError):
                    errors['base'] = 'cannot_connect'
        actions = {'login': '登录'}
        if self.mode == 'captcha':
            actions['resend'] = '重新发送短信验证码'
        actions.update({'back': '返回修改手机号或登录方式', 'cancel': '取消本次登录'})
        return self.async_show_form(step_id='credentials', data_schema=vol.Schema({
            vol.Optional('pin'): str,
            vol.Required('action', default='login'): vol.In(actions),
        }), errors=errors)

    async def async_step_device(self, user_input=None):
        candidates = {device_id(d): d for d in self.devices}
        errors = {}
        if user_input:
            identifier = user_input['device_id']
            selected = candidates.get(identifier)
            if selected is None:
                errors['base'] = 'no_devices'
            elif self.reauth_entry and identifier != self.reauth_entry.data['device_id']:
                errors['base'] = 'wrong_device'
            else:
                data = {'device_id': identifier, 'device': selected, 'access_token': self.api.token}
                if self.reauth_entry:
                    self.hass.config_entries.async_update_entry(self.reauth_entry, data=data, unique_id=identifier, version=2)
                    await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
                    return self.async_abort(reason='reauth_successful')
                await self.async_set_unique_id(identifier)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=selected.get('deviceNickname') or selected.get('name') or '飞利浦水健康', data=data)
        choices = {key: str(value.get('deviceNickname') or value.get('name') or f'净饮机 {index+1}')
                   for index, (key, value) in enumerate(candidates.items())}
        return self.async_show_form(step_id='device', data_schema=vol.Schema({vol.Required('device_id'): vol.In(choices)}), errors=errors)

    async def async_step_reauth(self, entry_data):
        self.reauth_entry = self.hass.config_entries.async_get_entry(self.context['entry_id'])
        return await self.async_step_user()

