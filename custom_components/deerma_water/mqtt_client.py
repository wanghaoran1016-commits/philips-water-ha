"""AWS shadow MQTT over TLS WebSocket. No account or payload logging."""
import asyncio
from contextlib import suppress
import json
import time
from urllib.parse import urlparse
import aiohttp
from .protocol import packet, mqtt_string, extract_packets, parse_publish, desired_payload, i2pro_desired_payload

class ShadowClient:
    def __init__(self, session, api, identifier, on_state, on_connection, on_auth):
        self.session, self.api, self.identifier = session, api, identifier
        self.on_state, self.on_connection, self.on_auth = on_state, on_connection, on_auth
        self.task = self.ws = None
        self.connected = False
        self.pending = {}
        self.on_desired = None
        self.sequence = 10
        self.version = -1
        self.prefix = f'$aws/things/{identifier}/shadow/'

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError): await self.task
            self.task = None

    async def _run(self):
        from .api_client import AuthError
        delay = 2
        while True:
            try:
                await self._connection()
            except asyncio.CancelledError:
                raise
            except AuthError:
                self.on_auth()
                return
            except Exception:
                pass  # No cloud exception text: it may contain a signed URL.
            finally:
                self.connected = False
                self.on_connection(False)
                for future in self.pending.values():
                    if not future.done(): future.set_exception(ConnectionError('Connection closed'))
                self.pending.clear()
                if self.ws:
                    await self.ws.close()
                    self.ws = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _connection(self):
        config = await self.api.mqtt_config(self.identifier)
        if urlparse(config['host']).scheme != 'wss': raise ValueError('TLS required')
        self.version = -1
        self.ws = await self.session.ws_connect(config['host'], protocols=['mqtt'], timeout=20)
        body = mqtt_string('MQTT') + bytes([4, 2, 0, 60]) + mqtt_string(config['clientID'])
        await self.ws.send_bytes(packet(0x10, body))
        buffer = bytearray()
        last_rx, last_ping = time.monotonic(), time.monotonic()
        deadline = time.monotonic() + 15
        subscribed = False
        while True:
            try:
                message = await self.ws.receive(timeout=10)
            except TimeoutError:
                message = None
            now = time.monotonic()
            if not subscribed and now > deadline: raise TimeoutError('MQTT handshake timeout')
            if now - last_rx > 90: raise TimeoutError('MQTT keepalive timeout')
            if now - last_ping >= 25:
                await self.ws.send_bytes(packet(0xC0)); last_ping = now
            if message is None: continue
            if message.type != aiohttp.WSMsgType.BINARY:
                if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise ConnectionError('WebSocket closed')
                continue
            last_rx = now; buffer.extend(message.data)
            for header, body in extract_packets(buffer):
                kind = header >> 4
                if kind == 2:
                    if body != bytes([0, 0]): raise ConnectionError('MQTT rejected connection')
                    topics = ['get/accepted', 'update/accepted', 'get/rejected', 'update/rejected']
                    await self.ws.send_bytes(packet(0x82, bytes([0, 1]) + b''.join(mqtt_string(self.prefix+t) + bytes([1]) for t in topics)))
                elif kind == 9:
                    if len(body) != 6 or body[:2] != bytes([0, 1]) or any(code not in (0, 1) for code in body[2:]):
                        raise ConnectionError('MQTT subscription rejected')
                    subscribed = self.connected = True
                    self.on_connection(True)
                    await self.ws.send_bytes(packet(0x30, mqtt_string(self.prefix+'get') + b'{}'))
                elif kind == 3:
                    topic, payload, ack = parse_publish(header, body)
                    if ack: await self.ws.send_bytes(packet(0x40, ack))
                    if not isinstance(payload, dict): continue
                    if topic.endswith('/rejected'): raise ConnectionError('Shadow request rejected')
                    version = payload.get('version', 0)
                    if not isinstance(version, int) or version < self.version: continue
                    self.version = version
                    shadow_state = payload.get('state')
                    if not isinstance(shadow_state, dict): continue
                    # Existing authorized subscription only. No new topics or writes.
                    if topic == self.prefix + 'update/accepted' and self.on_desired:
                        desired = shadow_state.get('desired')
                        if isinstance(desired, dict): self.on_desired(desired)
                    state = shadow_state.get('reported')
                    if isinstance(state, dict):
                        self.on_state(state)
                        for (field, value), future in list(self.pending.items()):
                            if field in state and str(state[field]) == str(value) and not future.done(): future.set_result(None)

    async def set_value(self, field, value):
        if not self.connected or not self.ws: raise ConnectionError('MQTT unavailable')
        if self.pending: raise RuntimeError('Wait for the previous command')
        payload = desired_payload(field, value, self.identifier)
        key = (field, value)
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            # QoS 0 avoids false broker-ACK success; wait for device reported state.
            await self.ws.send_bytes(packet(0x30, mqtt_string(self.prefix+'update') + json.dumps(payload).encode()))
            await asyncio.wait_for(future, 15)
        finally:
            self.pending.pop(key, None)


    async def set_i2pro_values(self, values, current):
        payload = i2pro_desired_payload(values, self.identifier)
        if not self.connected or not self.ws: raise ConnectionError('MQTT unavailable')
        if self.pending: raise RuntimeError('Wait for the previous command')
        # Unchanged fields may not be echoed by delta reports. Send the full pair,
        # await each changed field, then the coordinator verifies the full state.
        expected = {k:v for k,v in values.items()
                    if type(current.get(k)) is not int or current[k] != v}
        if not expected: return
        futures = {(k,v): asyncio.get_running_loop().create_future() for k,v in expected.items()}
        self.pending.update(futures)
        try:
            await self.ws.send_bytes(packet(0x30, mqtt_string(self.prefix+'update') + json.dumps(payload).encode()))
            await asyncio.wait_for(asyncio.gather(*futures.values()), 15)
        finally:
            for key, future in futures.items():
                self.pending.pop(key, None)
                if not future.done(): future.cancel()
