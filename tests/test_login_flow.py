import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

class Base:
    def __init_subclass__(cls, **kwargs): pass
    def async_show_form(self, **kwargs): return kwargs
    def async_abort(self, **kwargs): return kwargs

class LoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        package=types.ModuleType('flow_test');package.__path__=[str(Path(__file__).resolve().parents[1]/'custom_components/deerma_water')]
        ha=types.ModuleType('homeassistant');ha.config_entries=types.SimpleNamespace(ConfigFlow=Base)
        client=types.ModuleType('homeassistant.helpers.aiohttp_client');client.async_get_clientsession=lambda _:None
        modules=patch.dict(sys.modules,{'flow_test':package,'homeassistant':ha,'homeassistant.helpers':types.ModuleType('homeassistant.helpers'),'homeassistant.helpers.aiohttp_client':client})
        modules.start();self.addCleanup(modules.stop)
        self.mod=importlib.import_module('flow_test.config_flow');self.f=self.mod.ConfigFlow()
        self.f.mode='captcha';self.f.phone='+8613800000000'
        self.f.api=types.SimpleNamespace(request_captcha=AsyncMock(),login=AsyncMock(),devices=AsyncMock(return_value=[]))

    async def test_resend_cooldown_and_retry(self):
        self.assertEqual((await self.f.async_step_credentials({'action':'resend'}))['errors'],{})
        r=await self.f.async_step_credentials({'action':'resend'})
        self.assertEqual(r['errors']['base'],'sms_cooldown')
        self.f.api.request_captcha.assert_awaited_once()
        self.f.last_sms_sent-=61
        await self.f.async_step_credentials({'action':'resend'})
        self.assertEqual(self.f.api.request_captcha.await_count,2)
        self.f.api.login.assert_not_awaited()

    async def test_failed_send_does_not_trap_user(self):
        self.f.api.request_captcha.side_effect=self.mod.APIError('failed')
        self.assertEqual((await self.f.async_step_credentials({'action':'resend'}))['errors']['base'],'sms_send_failed')
        self.assertIsNone(self.f.last_sms_sent)
        self.f.api.request_captcha.side_effect=None
        self.assertEqual((await self.f.async_step_credentials({'action':'resend'}))['errors'],{})

    async def test_back_cancel_and_blank_code(self):
        entry=object();self.f.reauth_entry=entry
        self.assertEqual((await self.f.async_step_credentials({'action':'back'}))['step_id'],'user')
        self.assertEqual((await self.f.async_step_credentials({'action':'cancel'}))['reason'],'user_cancelled')
        self.assertIs(self.f.reauth_entry,entry)
        self.assertEqual((await self.f.async_step_credentials({'action':'login'}))['errors'],{'pin':'pin_required'})
        self.f.api.login.assert_not_awaited()

    async def test_invalid_code_and_password_login(self):
        self.f.api.login.side_effect=self.mod.AuthError('bad')
        self.assertEqual((await self.f.async_step_credentials({'pin':'000000'}))['errors']['base'],'invalid_auth')
        self.f.mode='password';self.f.api.login.side_effect=None
        r=await self.f.async_step_credentials()
        action=next(v for k,v in r['data_schema'].schema.items() if k.schema=='action')
        self.assertNotIn('resend',action.container)
        await self.f.async_step_credentials({'pin':'secret'})
        self.f.api.login.assert_awaited_with(self.f.phone,'secret','password')
