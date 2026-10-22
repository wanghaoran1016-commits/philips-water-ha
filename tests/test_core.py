"""Offline regression tests. Fake cloud/WebSocket; never contact real appliances."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'custom_components' / 'deerma_water'
package = types.ModuleType('deerma_test')
package.__path__ = [str(PKG)]
sys.modules['deerma_test'] = package
p = importlib.import_module('deerma_test.protocol')
t = importlib.import_module('deerma_test.trace')
a = importlib.import_module('deerma_test.api_client')
m = importlib.import_module('deerma_test.mqtt_client')
import aiohttp

class TraceTests(unittest.TestCase):
    def test_opt_in_timeout_reset_and_redaction(self):
        now = [0]
        trace = t.ControlTrace(lambda: now[0])
        trace.record('reported', {'TDS':6})
        self.assertEqual(trace.snapshot()['events'], [])
        trace.start({'TDS':6,'accessToken':'SECRET','Other':42})
        trace.record('desired_snapshot', {'IceCubeMode':1,'EnduserId':'SECRET','CommandType':'app'})
        self.assertEqual(trace.events[-1]['values'], {'IceCubeMode':1})
        trace.record('reported', {'TDS':6})
        self.assertEqual(len(trace.events),2)
        now[0]=300
        trace.record('reported', {'TDS':7})
        self.assertFalse(trace.active)
        self.assertEqual(len(trace.events),2)
        self.assertNotIn('SECRET',json.dumps(trace.snapshot()))
        trace.start({'TDS':8})
        self.assertEqual(len(trace.events),1)
        self.assertEqual(trace.events[0]['values'],{'TDS':8})

    def test_trace_bounded_and_export_is_copy(self):
        trace=t.ControlTrace(lambda:0)
        trace.start({})
        for i in range(205): trace.record('reported',{'TotalOutlet':i})
        self.assertEqual(len(trace.events),200)
        self.assertEqual(trace.dropped,5)
        d=trace.snapshot();d['events'][0]['values']['TotalOutlet']=999
        self.assertEqual(trace.events[0]['values']['TotalOutlet'],0)
        self.assertEqual(t.numeric_fields({'SetTemp':True,'LockKeySet':'1','IceWaterMode':float('nan')}),{})

class Helpers(unittest.TestCase):
    def test_four_observed_cooling_modes(self):
        for pair, label in [((0,0),'关闭'),((0,1),'仅冰水'),((1,1),'小冰和冰水'),((2,1),'大冰和冰水')]:
            self.assertEqual(p.i2pro_cooling_mode(dict(zip(('IceCubeMode','IceWaterMode'),pair))),label)
        for state in ({}, {'IceCubeMode':True,'IceWaterMode':1}, {'IceCubeMode':3,'IceWaterMode':1}, {'IceCubeMode':'1','IceWaterMode':1}):
            self.assertIsNone(p.i2pro_cooling_mode(state))
        for field in ('IceCubeMode','IceWaterMode'):
            with self.assertRaises(ValueError): p.desired_payload(field,1,'example')

    def test_digit_field_names_and_numeric_allowlist(self):
        d=p.diagnostics_snapshot({}, {'PC5IN1Life':100,'PC5in1FilterLife':99,'Filter2Remaining':87,'TotalOutlet':640,'LockKeySet':1,'token2':123,'Other2':456})
        self.assertEqual(d['schema_version'],2)
        self.assertEqual(d['reported_numeric_values'],{'PC5IN1Life':100,'PC5in1FilterLife':99,'TotalOutlet':640,'LockKeySet':1})
        self.assertIn('Filter2Remaining',d['reported_field_types'])
        self.assertNotIn('token2',d['reported_field_types'])

    def test_i2pro_write_allowlist(self):
        for pair in ((0,0),(0,1),(1,1),(2,1)):
            values=dict(zip(('IceCubeMode','IceWaterMode'),pair))
            self.assertEqual(p.i2pro_desired_payload(values,'example')['state']['desired']['IceCubeMode'],pair[0])
        for values in ({'IceCubeMode':1}, {'IceCubeMode':2,'IceWaterMode':0}, {'TouchBuzzerSet':True}, {'LockKeySet':0}, {'SetTemp':206}, {'PC5in1FilterReset':1}):
            with self.assertRaises(ValueError): p.i2pro_desired_payload(values,'example')
        self.assertEqual(p.i2pro_desired_payload({'TouchBuzzerSet':0},'example')['state']['desired']['TouchBuzzerSet'],0)

    def test_confirmed_preset_order(self):
        temps = ['常温','55℃','75℃','85℃','100℃','45℃','凉水','冰水']
        self.assertEqual([p.i2pro_preset_value('SetTemp',label) for label in temps],
                         [200,202,205,203,204,201,198,199])
        volumes = ['120 mL','150 mL','250 mL','350 mL','500 mL','800 mL','连续','150 mL','250 mL']
        self.assertEqual([p.i2pro_preset_value('SetOutlet',label) for label in volumes],
                         [8999,9000,9001,9002,9003,9004,9999,9000,9001])
        for field,labels in p.I2PRO_PRESETS.items():
            for label,code in labels.items():
                desired=p.i2pro_desired_payload({field:code},'example')['state']['desired']
                self.assertEqual(set(desired),{field,'CommandType','EnduserId'})
                self.assertEqual(desired[field],code)
        for values in ({'SetTemp':55},{'SetOutlet':250},{'SetTemp':True},{'SetTemp':202,'SetOutlet':9001}):
            with self.assertRaises(ValueError): p.i2pro_desired_payload(values,'example')
        with self.assertRaises(ValueError): p.i2pro_preset_value('SetTemp','60℃')

    def test_zero_is_not_missing(self):
        self.assertEqual(p.first_present({'a':0,'b':23},'a','b'), 0)
        self.assertIsNone(p.first_present({},'a'))

    def test_model_mapping_and_nonstandard_code(self):
        device = {'showAttributes':[{'id':'SetTemp','valueMapping':{'27':{'zh-CN':'55℃'},'0':'常温'}}]}
        self.assertEqual(p.enum_mapping(device,'SetTemp'), {'55℃':27,'常温':0})
        self.assertEqual(p.desired_payload('SetTemp',27,'example')['state']['desired']['SetTemp'],27)
        self.assertEqual(p.enum_mapping({},'SetTemp'),{})

    def test_ambiguous_or_invalid_mapping_disabled(self):
        for mapping in ({'0':'常温','1':'常温'}, {'bad':'55℃'}, {'0':None}):
            self.assertEqual(p.enum_mapping({'showAttributes':[{'id':'SetTemp','valueMapping':mapping}]},'SetTemp'),{})

    def test_unverified_commands_rejected(self):
        for field, value in [('IceStart',1),('SetTemp',True),('SetTemp','1'),('SetTemp',-1)]:
            with self.assertRaises(ValueError): p.desired_payload(field,value,'example')

    def test_diagnostics_does_not_copy_secrets(self):
        sentinel = 'PRIVATE-SENTINEL'
        device = {'device':{'id':sentinel},'deviceNickname':sentinel,'password':sentinel,
                  'showAttributes':[{'id':'SetTemp','valueMapping':{'0':'常温','1':sentinel}}]}
        state = {'accessToken':sentinel,'Nested':{'secret':sentinel},'Other':sentinel,
                 'phone':13900000000,'UserId':42,'IceUserId':7,'IceMode':0,'IceReady':False,
                 'TDS':0,'SetTemp':0,'CoolURL':'https://example/'+sentinel,'CoolHuge':float('inf')}
        snapshot = p.diagnostics_snapshot(device,state)
        encoded = json.dumps(snapshot)
        self.assertNotIn(sentinel,encoded)
        self.assertNotIn('13900000000',encoded)
        self.assertNotIn('IceUserId',encoded)
        self.assertEqual(snapshot['reported_numeric_values'],{'IceMode':0,'IceReady':False,'TDS':0,'SetTemp':0})
        self.assertEqual(snapshot['reported_field_types']['Nested'],'dict')

    def test_packet_fragment_and_multiple_packets(self):
        raw = p.packet(0x30,b'x'*300) + p.packet(0xD0)
        buf=bytearray(raw[:2]); self.assertEqual(p.extract_packets(buf),[])
        buf.extend(raw[2:]); self.assertEqual(p.extract_packets(buf),[(0x30,b'x'*300),(0xD0,b'')])
        self.assertEqual(buf,b'')

    def test_invalid_frame(self):
        with self.assertRaises(ValueError): p.extract_packets(bytearray(b'\x30\xff\xff\xff\xff'))
        with self.assertRaises(ValueError): p.parse_publish(0x32,b'\x00\x05abc')

    def test_publish_ack_and_payload(self):
        body = p.mqtt_string('a')+b'\x00\x19'+b'{"state":{"reported":{"TDS":0}}}'
        topic, value, ack = p.parse_publish(0x32,body)
        self.assertEqual(ack,b'\x00\x19'); self.assertEqual(topic,'a')
        self.assertEqual(value['state']['reported']['TDS'],0)

    def test_phone_normalization(self):
        self.assertEqual(a.normalize_phone('13800000000'),'+8613800000000')
        self.assertEqual(a.normalize_phone('8613800000000'),'+8613800000000')
        with self.assertRaises(ValueError): a.normalize_phone('invalid')

    def test_install_structure(self):
        manifest=json.loads((PKG/'manifest.json').read_text())
        self.assertEqual(manifest['domain'],PKG.name)
        self.assertEqual(manifest['requirements'],[])
        self.assertFalse((ROOT/'custom_components/manifest.json').exists())
        self.assertIn('Copyright (c) 2026 hlhk2017',(ROOT/'LICENSE').read_text())
        for path in PKG.rglob('*.py'): compile(path.read_text(),str(path),'exec')

class Response:
    def __init__(self,result,status=200): self.result,self.status=result,status
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def json(self): return self.result
    def raise_for_status(self):
        if self.status>=400: raise aiohttp.ClientError()

class Cloud:
    def __init__(self,result,status=200): self.result,self.status=result,status; self.calls=[]
    def request(self,*args,**kwargs): self.calls.append((args,kwargs)); return Response(self.result,self.status)

class APITests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_http_and_body(self):
        for result,status in [({},401),({'code':401},200),({'code':'403'},200)]:
            client=a.DeermaAPIClient(Cloud(result,status),'private')
            with self.assertRaises(a.AuthError): await client.devices()

    async def test_bad_response_not_logged_or_exposed(self):
        client=a.DeermaAPIClient(Cloud({'code':500,'message':'PRIVATE-SENTINEL'}),'private')
        with self.assertRaises(a.APIError) as ctx: await client.devices()
        self.assertNotIn('PRIVATE',str(ctx.exception))

    async def test_login_keeps_only_token(self):
        cloud=Cloud({'code':0,'data':{'accessToken':'private'}})
        client=a.DeermaAPIClient(cloud)
        self.assertEqual(await client.login('13800000000','secret','password'),'private')
        self.assertFalse(hasattr(client,'password'))
        self.assertEqual(cloud.calls[0][1]['json']['verify'],'password')

    async def test_device_enumeration(self):
        cloud=Cloud({'code':0,'data':[{'devices':[{'id':'one'},{'device':{'id':'two'}}]}]})
        devices=await a.DeermaAPIClient(cloud,'private').devices()
        self.assertEqual([p.device_id(x) for x in devices],['one','two'])

    async def test_sms_error_is_error(self):
        with self.assertRaises(a.APIError):
            await a.DeermaAPIClient(Cloud({'code':2})).request_captcha('13800000000')

class FakeAPI:
    async def mqtt_config(self,identifier): return {'host':'wss://example.invalid/mqtt','clientID':'example'}

class WebSocket:
    def __init__(self): self.inbox=asyncio.Queue(); self.sent=[]; self.closed=False
    async def send_bytes(self,data): self.sent.append(data)
    async def receive(self,timeout): return await asyncio.wait_for(self.inbox.get(),timeout)
    async def close(self): self.closed=True
    def push(self,data): self.inbox.put_nowait(types.SimpleNamespace(type=aiohttp.WSMsgType.BINARY,data=data))

class WSSession:
    def __init__(self,ws): self.ws=ws
    async def ws_connect(self,*args,**kwargs): return self.ws

async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate(): await asyncio.sleep(.001)

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ws=WebSocket(); self.states=[]; self.connections=[]
        self.client=m.ShadowClient(WSSession(self.ws),FakeAPI(),'example',self.states.append,self.connections.append,lambda:None)
        self.client.start()
        await until(lambda:bool(self.ws.sent))

    async def asyncTearDown(self): await self.client.stop()

    async def handshake(self):
        self.ws.push(p.packet(0x20,b'\x00\x00'))
        await until(lambda:len(self.ws.sent)>=2)
        self.ws.push(p.packet(0x90,b'\x00\x01\x01\x01\x01\x01'))
        await until(lambda:self.client.connected)

    def report(self,state,version=1):
        body=p.mqtt_string(self.client.prefix+'update/accepted') + b'\x00\x01' + json.dumps({'version':version,'state':{'reported':state}}).encode()
        self.ws.push(p.packet(0x32,body))

    async def test_connection_waits_for_ack(self):
        self.assertFalse(self.client.connected)
        await self.handshake()
        self.assertTrue(self.client.connected)

    async def test_write_waits_for_report_not_send(self):
        await self.handshake()
        task=asyncio.create_task(self.client.set_value('SetTemp',27))
        await until(lambda:bool(self.client.pending))
        self.assertFalse(task.done())
        self.report({'SetTemp':27})
        await asyncio.wait_for(task,1)
        self.assertEqual(self.states[-1],{'SetTemp':27})
        self.assertIn(p.packet(0x40,b'\x00\x01'),self.ws.sent)

    async def test_desired_only_does_not_confirm(self):
        await self.handshake()
        observed = []
        self.client.on_desired = observed.append
        task=asyncio.create_task(self.client.set_value('SetTemp',27))
        await until(lambda:bool(self.client.pending))
        payload={'version':1,'state':{'desired':{'SetTemp':27}}}
        self.ws.push(p.packet(0x30,p.mqtt_string(self.client.prefix+'update/accepted')+json.dumps(payload).encode()))
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.assertEqual(observed, [{'SetTemp':27}])
        self.report({'SetTemp':27},2); await asyncio.wait_for(task,1)

    async def test_combined_mode_sent_atomically_and_waits_for_both(self):
        await self.handshake()
        task=asyncio.create_task(self.client.set_i2pro_values({'IceCubeMode':2,'IceWaterMode':1},{'IceCubeMode':0,'IceWaterMode':0}))
        await until(lambda:len(self.client.pending)==2)
        frames=p.extract_packets(bytearray(self.ws.sent[-1]))
        _,payload,_=p.parse_publish(*frames[0])
        self.assertEqual(payload['state']['desired']['IceCubeMode'],2)
        self.assertEqual(payload['state']['desired']['IceWaterMode'],1)
        self.report({'IceCubeMode':2},1)
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.report({'IceWaterMode':1},2)
        await asyncio.wait_for(task,1)
        self.assertFalse(self.client.pending)

    async def test_mode_delta_and_buzzer(self):
        await self.handshake()
        task=asyncio.create_task(self.client.set_i2pro_values({'IceCubeMode':1,'IceWaterMode':1},{'IceCubeMode':2,'IceWaterMode':1}))
        await until(lambda:len(self.client.pending)==1)
        with self.assertRaises(RuntimeError):
            await self.client.set_i2pro_values({'TouchBuzzerSet':0},{'TouchBuzzerSet':1})
        self.report({'IceCubeMode':1},1); await asyncio.wait_for(task,1)
        task=asyncio.create_task(self.client.set_i2pro_values({'TouchBuzzerSet':0},{'TouchBuzzerSet':1}))
        await until(lambda:bool(self.client.pending))
        self.report({'TouchBuzzerSet':0},2); await asyncio.wait_for(task,1)
        sent=len(self.ws.sent)
        await self.client.set_i2pro_values({'TouchBuzzerSet':0},{'TouchBuzzerSet':0})
        self.assertEqual(len(self.ws.sent),sent)

    async def test_i2pro_preset_waits_for_report(self):
        await self.handshake()
        for version,field,value,previous in [(1,'SetTemp',202,199),(2,'SetOutlet',9003,9001)]:
            task=asyncio.create_task(self.client.set_i2pro_values({field:value},{field:previous}))
            await until(lambda:bool(self.client.pending))
            frames=p.extract_packets(bytearray(self.ws.sent[-1]))
            _,payload,_=p.parse_publish(*frames[0])
            self.assertEqual(payload['state']['desired'][field],value)
            self.assertFalse(task.done())
            self.report({field:value},version); await asyncio.wait_for(task,1)

    async def test_combined_disconnect_cleanup(self):
        await self.handshake()
        task=asyncio.create_task(self.client.set_i2pro_values({'IceCubeMode':2,'IceWaterMode':1},{'IceCubeMode':0,'IceWaterMode':0}))
        await until(lambda:len(self.client.pending)==2)
        await self.client.stop()
        with self.assertRaises(ConnectionError): await task
        self.assertFalse(self.client.pending)

    async def test_stale_version_ignored(self):
        await self.handshake()
        self.report({'TDS':7},8); await until(lambda:bool(self.states))
        self.report({'TDS':9},7); await asyncio.sleep(.01)
        self.assertEqual(self.states,[{'TDS':7}])

    async def test_stop_does_not_reconnect(self):
        await self.handshake()
        await self.client.stop()
        self.assertFalse(self.client.connected); self.assertTrue(self.ws.closed)
        self.assertIsNone(self.client.task)

    async def test_concurrent_commands_rejected(self):
        await self.handshake()
        task=asyncio.create_task(self.client.set_value('SetTemp',27))
        await until(lambda:bool(self.client.pending))
        with self.assertRaises(RuntimeError): await self.client.set_value('SetOutlet',0)
        self.report({'SetTemp':27}); await asyncio.wait_for(task,1)

    async def test_disconnect_fails_pending_command(self):
        await self.handshake()
        task=asyncio.create_task(self.client.set_value('SetTemp',27))
        await until(lambda:bool(self.client.pending))
        await self.client.stop()
        with self.assertRaises(ConnectionError): await task

if __name__=='__main__': unittest.main()
