"""
WebSocket Connection Manager
"""
import asyncio
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
    
    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
    
    # A half-dead client socket can make send_json wait indefinitely, which used
    # to hold admin requests (withdrawal approval, buyouts) for minutes.
    SEND_TIMEOUT_S = 5.0

    async def send_personal(self, message: dict, user_id: str):
        websocket = self.active_connections.get(user_id)
        if websocket:
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=self.SEND_TIMEOUT_S)
            except asyncio.TimeoutError:
                self.disconnect(user_id)
            except Exception:
                pass
    
    async def broadcast(self, message: dict):
        async def _one(user_id, websocket):
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=self.SEND_TIMEOUT_S)
            except Exception:
                self.disconnect(user_id)
        # in parallel: one slow client must not delay everybody else
        await asyncio.gather(*(_one(u, w) for u, w in list(self.active_connections.items())))


# Global manager instance
manager = ConnectionManager()

# Online users tracking
online_users = set()
last_activity = {}
