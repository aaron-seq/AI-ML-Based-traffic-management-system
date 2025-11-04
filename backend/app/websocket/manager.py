"""
WebSocket Manager for the AI Traffic Management System
"""

import asyncio
from typing import List

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..services.adaptive_traffic_manager import AdaptiveTrafficManager


class WebSocketManager(LoggerMixin):
    """Manages WebSocket connections and broadcasts"""

    def __init__(self):
        super().__init__()
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.logger.info("New WebSocket connection established")

    def disconnect(self, websocket: WebSocket):
        """Disconnect a WebSocket"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            self.logger.info("WebSocket connection closed")

    async def broadcast(self, message: str):
        """Broadcast a message to all connected clients"""
        for connection in self.active_connections:
            if connection.client_state == WebSocketState.CONNECTED:
                await connection.send_text(message)

    async def broadcast_traffic_updates(self, traffic_manager: AdaptiveTrafficManager):
        """Continuously broadcast traffic updates"""
        while True:
            try:
                status = await traffic_manager.get_current_status()
                await self.broadcast(status.json())

                await asyncio.sleep(settings.websocket_update_interval)

            except Exception as e:
                self.logger.exception(
                    "Error during WebSocket broadcast",
                    extra={"error": str(e)}
                )
                # Avoid spamming logs in case of persistent errors
                await asyncio.sleep(5)
