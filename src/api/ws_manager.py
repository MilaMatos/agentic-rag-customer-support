from collections import defaultdict
from typing import Any
from fastapi import WebSocket


class ConnectionManager:
    """Gerenciador de conexões WebSocket isoladas por tenant_id e perfil."""

    def __init__(self) -> None:
        # (tenant_id, session_id) -> set[WebSocket]
        self._client_connections: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        # tenant_id -> set[WebSocket]
        self._agent_connections: dict[str, set[WebSocket]] = defaultdict(set)
        # tenant_id -> set[WebSocket]
        self._specialist_connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect_client(self, websocket: WebSocket, tenant_id: str, session_id: str) -> None:
        await websocket.accept()
        self._client_connections[(tenant_id, session_id)].add(websocket)

    def disconnect_client(self, websocket: WebSocket, tenant_id: str, session_id: str) -> None:
        self._client_connections[(tenant_id, session_id)].discard(websocket)

    async def connect_agent(self, websocket: WebSocket, tenant_id: str) -> None:
        await websocket.accept()
        self._agent_connections[tenant_id].add(websocket)

    def disconnect_agent(self, websocket: WebSocket, tenant_id: str) -> None:
        self._agent_connections[tenant_id].discard(websocket)

    async def connect_specialist(self, websocket: WebSocket, tenant_id: str) -> None:
        await websocket.accept()
        self._specialist_connections[tenant_id].add(websocket)

    def disconnect_specialist(self, websocket: WebSocket, tenant_id: str) -> None:
        self._specialist_connections[tenant_id].discard(websocket)

    @staticmethod
    async def _broadcast(sockets: set[WebSocket], payload: dict[str, Any]) -> None:
        mortos: list[WebSocket] = []
        for ws in list(sockets):
            try:
                await ws.send_json(payload)
            except Exception:
                mortos.append(ws)
        for ws in mortos:
            sockets.discard(ws)

    async def send_to_client(self, tenant_id: str, session_id: str, event_type: str, data: dict[str, Any]) -> None:
        sockets = self._client_connections.get((tenant_id, session_id))
        if sockets:
            await self._broadcast(sockets, {"type": event_type, "data": data})

    async def send_to_agents(self, tenant_id: str, event_type: str, data: dict[str, Any]) -> None:
        sockets = self._agent_connections.get(tenant_id)
        if sockets:
            await self._broadcast(sockets, {"type": event_type, "data": data})

    async def send_to_specialists(self, tenant_id: str, event_type: str, data: dict[str, Any]) -> None:
        sockets = self._specialist_connections.get(tenant_id)
        if sockets:
            await self._broadcast(sockets, {"type": event_type, "data": data})


ws_manager = ConnectionManager()